'use client';

import { signIn } from 'next-auth/react';
import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

function SignInContent() {
  const params = useSearchParams();
  const callbackUrl = params.get('callbackUrl') || '/command-center';

  return (
    <main style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'radial-gradient(circle at 15% 0%, rgba(90,162,255,.18), transparent 32rem), #050914',
      fontFamily: 'Arial, Helvetica, sans-serif',
    }}>
      <div style={{
        border: '1px solid #26364f',
        background: 'rgba(14,23,38,.95)',
        borderRadius: 12,
        padding: '48px 40px',
        maxWidth: 400,
        width: '90%',
        textAlign: 'center',
        boxShadow: '0 20px 40px rgba(0,0,0,.4)',
      }}>
        <div style={{ color: '#eef5ff', fontSize: 22, fontWeight: 700, marginBottom: 8, letterSpacing: -0.5 }}>
          TRADE<span style={{ color: '#5aa2ff' }}>GATE</span>
          <span style={{ color: '#9fb0c6', fontSize: 12, marginLeft: 8 }}>v2</span>
        </div>
        <p style={{ color: '#9fb0c6', fontSize: 14, marginBottom: 32, lineHeight: 1.6 }}>
          Sign in with Google to access the command center. Your session is logged for access control and analytics.
        </p>
        <button
          onClick={() => signIn('google', { callbackUrl })}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            width: '100%',
            padding: '14px 24px',
            background: '#fff',
            color: '#1f2937',
            border: 'none',
            borderRadius: 8,
            fontSize: 15,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          <svg width="18" height="18" viewBox="0 0 18 18">
            <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
            <path d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.909-2.258c-.806.54-1.837.86-3.047.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853"/>
            <path d="M3.964 10.707A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z" fill="#FBBC05"/>
            <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961L3.964 7.293C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
          </svg>
          Continue with Google
        </button>
        <p style={{ color: '#9fb0c6', fontSize: 12, marginTop: 24, lineHeight: 1.5 }}>
          By signing in you agree to our terms. Access is logged for security and analytics.
        </p>
      </div>
    </main>
  );
}

export default function SignInPage() {
  return (
    <Suspense>
      <SignInContent />
    </Suspense>
  );
}
