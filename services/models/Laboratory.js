const mongoose = require('mongoose');

const laboratorySchema = new mongoose.Schema({
    nombre: { type: String, required: true },
    tipo: { type: String, required: true },
    capacidad: { type: Number, required: true },
    estado: { type: String, default: 'Disponible' }
}, { timestamps: true });

module.exports = mongoose.model('Laboratory', laboratorySchema);