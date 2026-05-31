import { NextRequest, NextResponse } from 'next/server';

const YT_BASE = 'https://www.googleapis.com/youtube/v3';
// Cache search results for 10 minutes to protect daily quota (10 000 units/day)
const REVALIDATE = 600;

export async function GET(req: NextRequest) {
  const apiKey = process.env.YOUTUBE_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: 'YOUTUBE_API_KEY not configured' }, { status: 503 });
  }

  const { searchParams } = req.nextUrl;
  const q = searchParams.get('q') || 'stock market today';
  const maxResults = Math.min(Number(searchParams.get('max') || 6), 12);
  const type = searchParams.get('type') || 'video'; // video | channel | playlist

  const url = new URL(`${YT_BASE}/search`);
  url.searchParams.set('part', 'snippet');
  url.searchParams.set('q', q);
  url.searchParams.set('maxResults', String(maxResults));
  url.searchParams.set('type', type);
  url.searchParams.set('order', 'relevance');
  url.searchParams.set('safeSearch', 'strict');
  url.searchParams.set('key', apiKey);

  try {
    const res = await fetch(url.toString(), { next: { revalidate: REVALIDATE } });
    if (!res.ok) {
      const err = await res.json();
      return NextResponse.json({ error: err?.error?.message || 'YouTube API error' }, { status: res.status });
    }
    const data = await res.json();
    // Trim response to only what the UI needs
    const items = (data.items || []).map((item: Record<string, unknown>) => {
      const snippet = item.snippet as Record<string, unknown>;
      const id = item.id as Record<string, unknown>;
      return {
        videoId: id?.videoId,
        channelId: id?.channelId,
        title: snippet?.title,
        description: snippet?.description,
        thumbnail: (snippet?.thumbnails as Record<string, {url: string}>)?.medium?.url,
        channel: snippet?.channelTitle,
        publishedAt: snippet?.publishedAt,
        url: id?.videoId ? `https://www.youtube.com/watch?v=${id.videoId}` : null,
      };
    });
    return NextResponse.json({ ok: true, query: q, count: items.length, items }, {
      headers: { 'Cache-Control': `public, s-maxage=${REVALIDATE}, stale-while-revalidate=60` },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
