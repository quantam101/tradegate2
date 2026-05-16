import type { Metadata } from 'next';
import './style.css';

export const metadata: Metadata = {
  title: 'GMAOS Command Center',
  description: 'Zero-spend, declarative, local-first multi-agent operating system command center.'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
