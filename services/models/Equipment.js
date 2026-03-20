const mongoose = require('mongoose');

const equipmentSchema = new mongoose.Schema({
    nombre: { type: String, required: true },
    tipo: { type: String, enum: ['equipo', 'herramienta', 'reactivo'], required: true },
    estado: { type: String, enum: ['Operativo', 'Mantenimiento', 'Dañado'], default: 'Operativo' },
    ubicacion: { type: String, required: true },
    id_laboratorio: { type: mongoose.Schema.Types.ObjectId, ref: 'Laboratory' },
    
    // Stock
    stock_actual: { type: Number, default: 0 },
    umbral_minimo: { type: Number, default: 5 },
    limite_reserva_usuario: { type: Number, default: 0 }, // 0 = sin límite
    
    // Restricciones
    solo_docente: { type: Boolean, default: false },
    fecha_vencimiento: { type: Date },
    url_imagen: { type: String }
}, { timestamps: true });

module.exports = mongoose.model('Equipment', equipmentSchema);