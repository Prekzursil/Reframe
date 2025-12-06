const User = require('../models/User');
const { validatePassword } = require('../utils/password');
const bcrypt = require('bcrypt');

const authenticateWithPassword = async (email, password) => {
  const user = await User.findOne({ email: email.toLowerCase() });
  if (!user) return null;

  const isValid = await validatePassword(password, user.password);
  if (!isValid) return null;

  user.lastLoginAt = new Date();
  await user.save();
  return user;
};

const createUser = async (userData) => {
  const { email, password } = userData;
  
  if (!email || !password) {
    throw new Error('Email and password are required');
  }

  // Check if user already exists
  const existingUser = await User.findOne({ email: email.toLowerCase() });
  if (existingUser) {
    throw new Error('User already exists');
  }

  // Hash password
  const salt = await bcrypt.genSalt(10);
  const hashedPassword = await bcrypt.hash(password, salt);

  // Create new user
  const user = new User({
    email: email.toLowerCase(),
    password: hashedPassword
  });

  await user.save();
  return user;
};

const getUser = async (userId) => {
  return await User.findById(userId);
};

const updateUser = async (userId, updates) => {
  const user = await User.findById(userId);
  if (!user) {
    throw new Error('User not found');
  }

  // Only allow updating certain fields
  const allowedUpdates = ['email'];
  const updateKeys = Object.keys(updates);
  const isValidOperation = updateKeys.every(key => allowedUpdates.includes(key));

  if (!isValidOperation) {
    throw new Error('Invalid updates');
  }

  updateKeys.forEach(key => {
    user[key] = updates[key];
  });

  await user.save();
  return user;
};

module.exports = {
  authenticateWithPassword,
  createUser,
  getUser,
  updateUser
};