const mongoose = require('mongoose');

const connectDB = async () => {
    try {
        // Usa la variable de entorno, o un fallback para desarrollo local
        const mongoURI = process.env.MONGODB_URI || 'mongodb://localhost:27017/ucb_inventory';
        await mongoose.connect(mongoURI);
        console.log('MongoDB Conectado al Microservicio de Inventario');
    } catch (error) {
        console.error('Error de conexión a MongoDB:', error);
        process.exit(1);
    }
};

module.exports = connectDB;