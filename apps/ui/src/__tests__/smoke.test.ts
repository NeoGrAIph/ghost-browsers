import { describe, it, expect } from 'vitest';
import { createUrl } from '../utils/url';

describe('url helpers', () => {
  it('joins paths without duplicate slashes', () => {
    expect(createUrl('http://localhost:8000/', '/sessions')).toBe('http://localhost:8000/sessions');
  });
});
