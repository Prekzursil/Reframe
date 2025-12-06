const jwt = require('jsonwebtoken');

const generateAccessToken = (user) => {
  const payload = {
    sub: user._id
  };
  return jwt.sign(payload, process.env.JWT_SECRET, { expiresIn: '15m' });
};

const generateRefreshToken = (user) => {
  const payload = {
    sub: user._id
  };
  return jwt.sign(payload, process.env.REFRESH_TOKEN_SECRET, { expiresIn: '30d' });
};

module.exports = {
  generateAccessToken,
  generateRefreshToken
};
