import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Genesis — Autonomous SRE',
  description: 'Real-time autonomous incident response dashboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-bg-base min-h-screen">{children}</body>
    </html>
  )
}
