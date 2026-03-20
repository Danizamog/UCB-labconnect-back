const mongoose = require('mongoose');

const historySchema = new mongoose.Schema({
    equipoId: { type: mongoose.Schema.Types.ObjectId, ref: 'Equipment', required: true },
    usuarioId: { type: String, required: true },
    tipo_movimiento: { type: String, enum: ['ingreso', 'consumo', 'devolucion'], required: true },
    cantidad: { type: Number, required: true },
    stock_resultante: { type: Number, required: true },
    fecha: { type: Date, default: Date.now }
});

module.exports = mongoose.model('InventoryHistory', historySchema);