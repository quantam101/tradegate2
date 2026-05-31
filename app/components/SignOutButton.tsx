'use client';

import { signOut } from 'next-auth/react';

export default function SignOutButton() {
  return (
    <button
      onClick={() => signOut({ callbackUrl: '/' })}
      style={{
        padding: '6px 14px',
        background: 'transparent',
        border: '1px solid #26364f',
        borderRadius: 999,
        color: '#9fb0c6',
        fontSize: 12,
        cursor: 'pointer',
        fontFamily: 'inherit',
      }}
    >
      Sign out
    </button>
  );
}
