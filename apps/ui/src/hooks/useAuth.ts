import { useContext } from 'react';
import { AuthContext } from '../providers/AuthProvider';

/**
 * Hook returning the AuthContext value with runtime guard against missing provider.
 */
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }

  return context;
};
