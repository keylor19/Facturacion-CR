// Catálogos v4.4 (tomados de los XSD oficiales de Hacienda).

export const TIPOS_DOCUMENTO = {
  '01': 'Factura electrónica', '04': 'Tiquete electrónico', '02': 'Nota de débito',
  '03': 'Nota de crédito', '08': 'Factura de compra', '09': 'Factura de exportación',
};

export const TIPOS_IDENTIFICACION = {
  '01': 'Cédula física', '02': 'Cédula jurídica', '03': 'DIMEX', '04': 'NITE',
  '05': 'Extranjero no domiciliado', '06': 'No contribuyente',
};

export const CONDICIONES_VENTA = {
  '01': 'Contado', '02': 'Crédito', '03': 'Consignación', '04': 'Apartado',
  '05': 'Arrendamiento con opción de compra', '06': 'Arrendamiento en función financiera',
  '07': 'Cobro a favor de un tercero', '08': 'Servicios prestados al Estado a crédito',
  '10': 'Venta a crédito en IVA hasta 90 días', '12': 'Venta de mercancía no nacionalizada',
  '13': 'Venta de bienes usados no contribuyente', '14': 'Arrendamiento operativo',
  '15': 'Arrendamiento financiero', '99': 'Otros',
};

export const MEDIOS_PAGO = {
  '01': 'Efectivo', '02': 'Tarjeta', '03': 'Cheque', '04': 'Transferencia / depósito',
  '05': 'Recaudado por terceros', '06': 'SINPE Móvil', '07': 'Plataforma digital', '99': 'Otros',
};

export const TARIFAS_IVA = {
  '08': ['Tarifa general 13%', 13], '07': ['Tarifa transitoria 8%', 8], '04': ['Tarifa reducida 4%', 4],
  '06': ['Transitorio 4%', 4], '03': ['Tarifa reducida 2%', 2], '02': ['Tarifa reducida 1%', 1],
  '09': ['Tarifa reducida 0.5%', 0.5], '01': ['Tarifa 0% (Art. 32 RLIVA)', 0], '05': ['Transitorio 0%', 0],
  '11': ['0% sin derecho a crédito', 0], '10': ['Exenta', 0],
};

export const DESCUENTOS = {
  '07': 'Descuento comercial', '06': 'Promocional', '04': 'Por volumen', '05': 'Por temporada',
  '08': 'Por frecuencia', '09': 'Sostenido', '03': 'Bonificación', '01': 'Regalía',
  '02': 'Regalía IVA cobrado al cliente', '99': 'Otros',
};

export const UNIDADES = {
  Unid: 'Unidad', Sp: 'Servicios profesionales', Os: 'Otro tipo de servicio', h: 'Hora',
  Spe: 'Servicios personales', St: 'Servicios técnicos', Al: 'Alquiler habitacional', Alc: 'Alquiler comercial',
  Cm: 'Comisiones', I: 'Intereses', Kg: 'Kilogramo', G: 'Gramo', L: 'Litro', mL: 'Mililitro', Gal: 'Galón',
  M: 'Metro', 'm²': 'Metro cuadrado', 'm³': 'Metro cúbico', Km: 'Kilómetro', D: 'Día', Min: 'Minuto',
  kWh: 'Kilovatio hora', Oz: 'Onza', Qq: 'Quintal', Otros: 'Otros',
};

export const INSTITUCIONES_EXONERACION = {
  '01': 'Ministerio de Hacienda', '02': 'Ministerio de Relaciones Exteriores y Culto',
  '03': 'Ministerio de Agricultura y Ganadería', '04': 'Ministerio de Economía, Industria y Comercio',
  '05': 'Cruz Roja Costarricense', '06': 'Benemérito Cuerpo de Bomberos', '07': 'Asociación Obras del Espíritu Santo',
  '08': 'FECRUNAPA', '09': 'EARTH', '10': 'INCAE', '11': 'Junta de Protección Social', '12': 'ARESEP', '99': 'Otros',
};

export const TIPOS_DOC_REFERENCIA = {
  '01': 'Factura electrónica', '02': 'Nota de débito', '03': 'Nota de crédito', '04': 'Tiquete',
  '05': 'Nota de despacho', '06': 'Contrato', '07': 'Procedimiento', '08': 'Comprobante emitido en contingencia',
  '09': 'Devolución de mercadería', '10': 'Comprobante rechazado por Hacienda',
  '11': 'Sustituye factura rechazada por el receptor', '12': 'Sustituye factura de exportación',
  '13': 'Facturación mes vencido', '14': 'Comprobante de régimen especial', '15': 'Sustituye factura de compra',
  '16': 'Proveedor no domiciliado', '17': 'NC a factura de compra', '18': 'ND a factura de compra', '99': 'Otros',
};

export const CODIGOS_REFERENCIA = {
  '01': 'Anula documento', '02': 'Corrige texto', '04': 'Referencia a otro documento',
  '05': 'Sustituye comprobante provisional por contingencia', '06': 'Devolución de mercancía',
  '07': 'Sustituye comprobante electrónico', '08': 'Factura endosada', '09': 'Nota de crédito financiera',
  '10': 'Nota de débito financiera', '11': 'Proveedor no domiciliado',
  '12': 'Crédito por exoneración posterior', '99': 'Otros',
};

export const CONDICIONES_IMPUESTO = {
  '01': 'Genera crédito IVA', '02': 'Genera crédito parcial del IVA', '03': 'Bienes de capital',
  '04': 'Gasto corriente, no genera crédito', '05': 'Proporcionalidad',
};

export const SITUACIONES = {
  1: 'Normal', 2: 'Contingencia (sustituye comprobante provisional)', 3: 'Sin internet',
};
