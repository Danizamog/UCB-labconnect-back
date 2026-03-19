require('dotenv').config();
const express = require('express');
const cors = require('cors');
const connectDB = require('./src/config/db');
const inventoryRoutes = require('./src/routes/inventory.routes');

const app = express();

// Middlewares
app.use(express.json());
app.use(cors());

// Conexión a BD
connectDB();

// Rutas base del microservicio
app.use('/api/inventory', inventoryRoutes);

app.use((req, res) => res.status(404).json({ error: 'Ruta de inventario no encontrada' }));

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
    console.log(`Inventory Service corriendo en el puerto ${PORT}`);
});