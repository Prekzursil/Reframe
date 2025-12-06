const { getUser } = require('../../controllers/authController');
const jwt = require('jsonwebtoken');

const requireUser = async (req, res, next) => {
  console.log('Auth middleware called for path:', req.path);
  console.log('Authorization header:', req.headers.authorization);

  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    console.log('Authentication failed: No valid authorization header');
    return res.status(403).json({ error: 'Not authenticated' });
  }

  const token = authHeader.split(' ')[1];
  if (!token) {
    console.log('Authentication failed: No token found after Bearer prefix');
    return res.status(401).json({ message: 'Unauthorized' });
  }

  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    console.log('Token decoded successfully for user:', decoded.sub);
    
    const user = await getUser(decoded.sub);
    if (!user) {
      console.log('Authentication failed: User not found for ID:', decoded.sub);
      return res.status(401).json({ error: 'User not found' });
    }
    console.log('User authenticated successfully:', user.email || user._id);
    req.user = user;

    next();
  } catch (err) {
    console.error('Authentication error:', err);
    return res.status(403).json({ error: 'Invalid or expired token' });
  }
};

module.exports = {
  requireUser,
};