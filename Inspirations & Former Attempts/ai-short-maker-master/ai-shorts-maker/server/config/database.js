const mongoose = require('mongoose');

const connectDB = async () => {
  try {
    const conn = await mongoose.connect(process.env.DATABASE_URL, {
      // MongoDB connection options
      serverSelectionTimeoutMS: 5000, // Timeout after 5s instead of 30s
      socketTimeoutMS: 45000, // Close sockets after 45s of inactivity
    });

    console.log('MongoDB Connected:', conn.connection.host);
    
    // Set up error handlers for the connection
    conn.connection.on('error', err => {
      console.error('MongoDB error:', err);
    });

    conn.connection.on('disconnected', () => {
      console.warn('MongoDB disconnected');
    });

    conn.connection.on('reconnected', () => {
      console.info('MongoDB reconnected');
    });

    return conn;
  } catch (error) {
    console.error('MongoDB connection error:', error);
    // Rethrow the error to be handled by the caller
    throw error;
  }
};

module.exports = { connectDB };