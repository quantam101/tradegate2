import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth';
import SignOutButton from '@/app/components/SignOutButton';

export default async function CommandCenterLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions);

  return (
    <>
      <nav style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 24px',
        borderBottom: '1px solid #26364f',
        background: 'rgba(14,23,38,.95)',
        backdropFilter: 'blur(8px)',
        position: 'sticky',
        top: 0,
        zIndex: 50,
        fontFamily: 'Arial, Helvetica, sans-serif',
      }}>
        <div style={{ color: '#eef5ff', fontSize: 14, fontWeight: 700, letterSpacing: -0.3 }}>
          TRADE<span style={{ color: '#5aa2ff' }}>GATE</span>
          <span style={{ color: '#9fb0c6', fontSize: 11, marginLeft: 8 }}>Command Center</span>
        </div>
        {session?.user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {session.user.image && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={session.user.image}
                alt={session.user.name ?? 'User'}
                width={28}
                height={28}
                style={{ borderRadius: '50%', border: '1px solid #26364f' }}
              />
            )}
            <span style={{ color: '#9fb0c6', fontSize: 13 }}>{session.user.email}</span>
            <SignOutButton />
          </div>
        )}
      </nav>
      {children}
    </>
  );
}
