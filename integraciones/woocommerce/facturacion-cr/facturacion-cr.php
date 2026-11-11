<?php
/**
 * Plugin Name: Facturación Electrónica CR
 * Description: Emite la factura o el tiquete electrónico de Hacienda (v4.4) de cada pedido de WooCommerce por medio del API de Facturación CR.
 * Version: 1.0.0
 * Requires at least: 6.0
 * Requires PHP: 7.4
 * WC requires at least: 7.0
 * Text Domain: facturacion-cr
 * License: GPLv2 or later
 *
 * Cómo funciona:
 * - En el pago se pide la cédula (opcional). Con cédula se emite factura electrónica (01); sin cédula, tiquete (04).
 * - Al pasar el pedido a «Completado» (o «Procesando», según el ajuste) se envía a POST /facturas con
 *   referencia_externa = WC-<número de pedido>: si se reintenta, el API no duplica el comprobante.
 * - Cada producto puede tener su código CABYS y tarifa de IVA (pestaña «Facturación CR» del producto);
 *   si no, se usan los de los ajustes.
 */

if (!defined('ABSPATH')) {
    exit;
}

final class Facturacion_CR {
    const OPCION = 'facturacion_cr_ajustes';
    const META_CABYS = '_fcr_cabys';
    const META_TARIFA = '_fcr_tarifa_iva';
    const META_CEDULA = '_fcr_cedula';
    const META_TIPO_ID = '_fcr_tipo_identificacion';
    const META_FACTURA = '_fcr_factura_id';
    const META_CLAVE = '_fcr_clave';

    // Códigos de tarifa de IVA de Hacienda (CodigoTarifaIVA)
    const TARIFAS = array(
        '08' => '13% (general)', '04' => '4%', '03' => '2%', '02' => '1%', '09' => '0,5%', '10' => 'Exento', '01' => '0%',
    );

    public static function iniciar() {
        $yo = new self();
        add_action('admin_menu', array($yo, 'menu'));
        add_action('admin_init', array($yo, 'registrar_ajustes'));
        add_action('woocommerce_after_order_notes', array($yo, 'campo_cedula'));
        add_action('woocommerce_checkout_process', array($yo, 'validar_cedula'));
        add_action('woocommerce_checkout_create_order', array($yo, 'guardar_cedula'), 10, 2);
        add_action('woocommerce_order_status_changed', array($yo, 'al_cambiar_estado'), 10, 4);
        add_filter('woocommerce_product_data_tabs', array($yo, 'pestana_producto'));
        add_action('woocommerce_product_data_panels', array($yo, 'panel_producto'));
        add_action('woocommerce_process_product_meta', array($yo, 'guardar_producto'));
        add_action('add_meta_boxes', array($yo, 'caja_pedido'));
        add_action('admin_post_fcr_reintentar', array($yo, 'reintentar'));
    }

    private function ajustes() {
        return wp_parse_args(get_option(self::OPCION, array()), array(
            'url' => '', 'api_key' => '', 'cabys' => '', 'tarifa' => '08', 'cabys_envio' => '',
            'estado' => 'completed', 'actividad' => '',
        ));
    }

    /* ---------- Ajustes (WooCommerce → Facturación CR) ---------- */

    public function menu() {
        add_submenu_page('woocommerce', 'Facturación CR', 'Facturación CR', 'manage_woocommerce', 'facturacion-cr', array($this, 'pagina_ajustes'));
    }

    public function registrar_ajustes() {
        register_setting('facturacion_cr', self::OPCION, array('sanitize_callback' => array($this, 'limpiar_ajustes')));
    }

    public function limpiar_ajustes($v) {
        return array(
            'url' => esc_url_raw(rtrim(trim($v['url'] ?? ''), '/')),
            'api_key' => sanitize_text_field($v['api_key'] ?? ''),
            'cabys' => preg_replace('/\D/', '', $v['cabys'] ?? ''),
            'tarifa' => array_key_exists($v['tarifa'] ?? '', self::TARIFAS) ? $v['tarifa'] : '08',
            'cabys_envio' => preg_replace('/\D/', '', $v['cabys_envio'] ?? ''),
            'estado' => in_array($v['estado'] ?? '', array('completed', 'processing'), true) ? $v['estado'] : 'completed',
            'actividad' => preg_replace('/\D/', '', $v['actividad'] ?? ''),
        );
    }

    public function pagina_ajustes() {
        $a = $this->ajustes();
        $campo = function ($nombre, $etiqueta, $valor, $ayuda = '', $tipo = 'text') {
            printf('<tr><th><label for="fcr_%1$s">%2$s</label></th><td><input type="%5$s" class="regular-text" id="fcr_%1$s" name="%3$s[%1$s]" value="%4$s"><p class="description">%6$s</p></td></tr>',
                esc_attr($nombre), esc_html($etiqueta), esc_attr(self::OPCION), esc_attr($valor), esc_attr($tipo), esc_html($ayuda));
        };
        echo '<div class="wrap"><h1>Facturación Electrónica CR</h1><form method="post" action="options.php">';
        settings_fields('facturacion_cr');
        echo '<table class="form-table">';
        $campo('url', 'Dirección del servicio', $a['url'], 'Ej.: https://facturas.suproveedor.com/api/v1');
        $campo('api_key', 'API key', $a['api_key'], 'La que le entregó su proveedor (empieza con fcr_).', 'password');
        $campo('cabys', 'CABYS por defecto', $a['cabys'], 'Para productos que no tengan uno propio (13 dígitos).');
        echo '<tr><th>IVA por defecto</th><td><select name="' . esc_attr(self::OPCION) . '[tarifa]">';
        foreach (self::TARIFAS as $codigo => $texto) {
            printf('<option value="%s"%s>%s</option>', esc_attr($codigo), selected($a['tarifa'], $codigo, false), esc_html($texto));
        }
        echo '</select></td></tr>';
        $campo('cabys_envio', 'CABYS del envío', $a['cabys_envio'], 'Si cobra envío, código del servicio de transporte. Vacío = el envío no se factura.');
        $campo('actividad', 'Actividad económica (opcional)', $a['actividad'], 'Código de 6 dígitos si su empresa tiene varias.');
        echo '<tr><th>Emitir cuando el pedido pase a</th><td><select name="' . esc_attr(self::OPCION) . '[estado]">';
        printf('<option value="completed"%s>Completado</option>', selected($a['estado'], 'completed', false));
        printf('<option value="processing"%s>Procesando (pagado)</option>', selected($a['estado'], 'processing', false));
        echo '</select></td></tr></table>';
        submit_button('Guardar');
        echo '</form></div>';
    }

    /* ---------- Cédula en el pago ---------- */

    public function campo_cedula($checkout) {
        woocommerce_form_field('fcr_cedula', array(
            'type' => 'text', 'class' => array('form-row-wide'), 'label' => 'Cédula para factura electrónica (opcional)',
            'placeholder' => 'Sin guiones. Vacío = tiquete electrónico', 'maxlength' => 12,
        ), $checkout->get_value('fcr_cedula'));
    }

    public function validar_cedula() {
        $cedula = preg_replace('/\D/', '', $_POST['fcr_cedula'] ?? '');
        if ($cedula !== '' && (strlen($cedula) < 9 || strlen($cedula) > 12)) {
            wc_add_notice('La cédula debe tener entre 9 y 12 dígitos (sin guiones).', 'error');
        }
    }

    public function guardar_cedula($order, $data) {
        $cedula = preg_replace('/\D/', '', $_POST['fcr_cedula'] ?? '');
        if ($cedula !== '') {
            $order->update_meta_data(self::META_CEDULA, $cedula);
            // 9 dígitos física, 10 jurídica, 11-12 DIMEX
            $tipo = strlen($cedula) === 9 ? '01' : (strlen($cedula) === 10 ? '02' : '03');
            $order->update_meta_data(self::META_TIPO_ID, $tipo);
        }
    }

    /* ---------- CABYS e IVA por producto ---------- */

    public function pestana_producto($tabs) {
        $tabs['facturacion_cr'] = array('label' => 'Facturación CR', 'target' => 'fcr_datos_producto', 'priority' => 80);
        return $tabs;
    }

    public function panel_producto() {
        echo '<div id="fcr_datos_producto" class="panel woocommerce_options_panel">';
        woocommerce_wp_text_input(array('id' => self::META_CABYS, 'label' => 'Código CABYS', 'description' => '13 dígitos. Vacío = el de los ajustes.', 'desc_tip' => true));
        woocommerce_wp_select(array('id' => self::META_TARIFA, 'label' => 'IVA', 'options' => array('' => 'El de los ajustes') + self::TARIFAS));
        echo '</div>';
    }

    public function guardar_producto($post_id) {
        update_post_meta($post_id, self::META_CABYS, preg_replace('/\D/', '', $_POST[self::META_CABYS] ?? ''));
        $tarifa = $_POST[self::META_TARIFA] ?? '';
        update_post_meta($post_id, self::META_TARIFA, array_key_exists($tarifa, self::TARIFAS) ? $tarifa : '');
    }

    /* ---------- Emisión ---------- */

    public function al_cambiar_estado($order_id, $de, $a, $order) {
        if ($a === $this->ajustes()['estado']) {
            $this->emitir($order);
        }
    }

    private function medio_pago($order) {
        $metodo = $order->get_payment_method();
        if ($metodo === 'cod') {
            return '01';   // efectivo contra entrega
        }
        if ($metodo === 'bacs' || $metodo === 'cheque') {
            return $metodo === 'bacs' ? '04' : '03';
        }
        return '02';       // tarjeta u otra pasarela
    }

    private function armar($order) {
        $a = $this->ajustes();
        $lineas = array();
        foreach ($order->get_items() as $item) {
            $producto = $item->get_product();
            $id = $producto ? ($producto->get_parent_id() ?: $producto->get_id()) : 0;
            $cantidad = max(1, (float) $item->get_quantity());
            $subtotal = (float) $item->get_subtotal();   // sin IVA, antes de cupones
            $total = (float) $item->get_total();         // sin IVA, después de cupones
            $linea = array(
                'codigo_cabys' => get_post_meta($id, self::META_CABYS, true) ?: $a['cabys'],
                'descripcion' => mb_substr($item->get_name(), 0, 200),
                'cantidad' => (string) $cantidad,
                'unidad_medida' => $producto && $producto->is_virtual() ? 'Sp' : 'Unid',
                'precio_unitario' => number_format($subtotal / $cantidad, 5, '.', ''),
                'codigo_tarifa_iva' => get_post_meta($id, self::META_TARIFA, true) ?: $a['tarifa'],
            );
            if ($producto && $producto->get_sku()) {
                $linea['codigo_comercial'] = mb_substr($producto->get_sku(), 0, 20);
            }
            if ($subtotal - $total > 0.004) {
                $linea['descuento'] = number_format($subtotal - $total, 5, '.', '');
                $linea['codigo_descuento'] = '07';
            }
            $lineas[] = $linea;
        }
        if ($a['cabys_envio'] && (float) $order->get_shipping_total() > 0) {
            $lineas[] = array(
                'codigo_cabys' => $a['cabys_envio'], 'descripcion' => 'Envío', 'cantidad' => '1', 'unidad_medida' => 'Sp',
                'precio_unitario' => number_format((float) $order->get_shipping_total(), 5, '.', ''), 'codigo_tarifa_iva' => $a['tarifa'],
            );
        }
        $nombre = trim($order->get_billing_company() ?: $order->get_formatted_billing_full_name());
        $cedula = $order->get_meta(self::META_CEDULA);
        $datos = array(
            'tipo_documento' => $cedula ? '01' : '04',
            'referencia_externa' => 'WC-' . $order->get_order_number(),
            'moneda' => $order->get_currency() === 'USD' ? 'USD' : 'CRC',
            'productos' => $lineas,
            'medios_pago' => array(array('tipo' => $this->medio_pago($order))),
            'notas' => 'Pedido en línea #' . $order->get_order_number(),
        );
        if ($a['actividad']) {
            $datos['codigo_actividad_emisor'] = $a['actividad'];
        }
        if ($cedula) {
            $datos['receptor'] = array('nombre' => mb_substr($nombre, 0, 100), 'tipo_identificacion' => $order->get_meta(self::META_TIPO_ID) ?: '01',
                'numero_identificacion' => $cedula, 'correo' => $order->get_billing_email());
        } elseif ($nombre) {
            $datos['receptor'] = array('nombre' => mb_substr($nombre, 0, 100));   // tiquete con solo el nombre
        }
        return $datos;
    }

    public function emitir($order) {
        if ($order->get_meta(self::META_FACTURA)) {
            return;   // ya facturado
        }
        $a = $this->ajustes();
        if (!$a['url'] || !$a['api_key']) {
            $order->add_order_note('Facturación CR: falta configurar la dirección del servicio y la API key.');
            return;
        }
        $respuesta = wp_remote_post($a['url'] . '/facturas', array(
            'timeout' => 30,
            'headers' => array('Content-Type' => 'application/json', 'X-API-Key' => $a['api_key']),
            'body' => wp_json_encode($this->armar($order)),
        ));
        if (is_wp_error($respuesta)) {
            $order->add_order_note('Facturación CR: no hubo conexión con el servicio (' . $respuesta->get_error_message() . '). Use «Reintentar» en el pedido.');
            return;
        }
        $codigo = wp_remote_retrieve_response_code($respuesta);
        $cuerpo = json_decode(wp_remote_retrieve_body($respuesta), true);
        if ($codigo >= 200 && $codigo < 300 && !empty($cuerpo['factura_id'])) {
            $order->update_meta_data(self::META_FACTURA, sanitize_text_field($cuerpo['factura_id']));
            $order->update_meta_data(self::META_CLAVE, sanitize_text_field($cuerpo['clave'] ?? ''));
            $order->save();
            $order->add_order_note(sprintf('Facturación CR: comprobante emitido. Clave %s (%s). Al aceptarlo Hacienda, el cliente lo recibe por correo.',
                $cuerpo['clave'] ?? '', $cuerpo['estado'] ?? ''));
            return;
        }
        $detalle = is_array($cuerpo) && isset($cuerpo['detail']) ? (is_string($cuerpo['detail']) ? $cuerpo['detail'] : wp_json_encode($cuerpo['detail'])) : 'HTTP ' . $codigo;
        $order->add_order_note('Facturación CR: no se pudo emitir: ' . mb_substr($detalle, 0, 500));
    }

    /* ---------- Caja en el pedido ---------- */

    public function caja_pedido() {
        $pantalla = function_exists('wc_get_page_screen_id') ? wc_get_page_screen_id('shop-order') : 'shop_order';
        add_meta_box('fcr_pedido', 'Facturación CR', array($this, 'contenido_caja'), $pantalla, 'side');
    }

    public function contenido_caja($objeto) {
        $order = $objeto instanceof WC_Order ? $objeto : wc_get_order($objeto->ID);
        if (!$order) {
            return;
        }
        $clave = $order->get_meta(self::META_CLAVE);
        if ($clave) {
            echo '<p>Comprobante emitido.<br><small style="word-break:break-all">Clave ' . esc_html($clave) . '</small></p>';
            return;
        }
        $url = wp_nonce_url(admin_url('admin-post.php?action=fcr_reintentar&pedido=' . $order->get_id()), 'fcr_reintentar_' . $order->get_id());
        echo '<p>Sin comprobante.</p><a class="button" href="' . esc_url($url) . '">Emitir ahora</a>';
    }

    public function reintentar() {
        $id = absint($_GET['pedido'] ?? 0);
        if (!current_user_can('edit_shop_orders') || !wp_verify_nonce($_GET['_wpnonce'] ?? '', 'fcr_reintentar_' . $id)) {
            wp_die('No autorizado');
        }
        $order = wc_get_order($id);
        if ($order) {
            $this->emitir($order);
        }
        wp_safe_redirect(wp_get_referer() ?: admin_url('edit.php?post_type=shop_order'));
        exit;
    }
}

add_action('plugins_loaded', function () {
    if (class_exists('WooCommerce')) {
        Facturacion_CR::iniciar();
    }
});

// Compatible con el almacenamiento de pedidos de alto rendimiento (HPOS)
add_action('before_woocommerce_init', function () {
    if (class_exists(\Automattic\WooCommerce\Utilities\FeaturesUtil::class)) {
        \Automattic\WooCommerce\Utilities\FeaturesUtil::declare_compatibility('custom_order_tables', __FILE__, true);
    }
});
