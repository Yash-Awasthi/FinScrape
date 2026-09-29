// Live-news YouTube channels for the LiveTV panel (iframe embeds). Only channels
// whose live_stream embed played on 29 Sep 2026; the rest stream part-time or block
// embedding and showed "This video is unavailable". The first one plays by default.

export interface Channel {
  name: string;
  country: string;
  channelId: string;
}

export const CHANNELS: Channel[] = [
  { name: "DW News", country: "Germany", channelId: "UCknLrEdhRCp1aegoMqRaCZg" },
  { name: "Al Jazeera English", country: "Qatar", channelId: "UCNye-wNBqNL5ZzHSJj3l8Bg" },
  { name: "France 24 English", country: "France", channelId: "UCQfwfsi5VrQ8yKZ-UWmAEFg" },
  { name: "CNN", country: "USA", channelId: "UCupvZG-5ko_eiXAupbDfxWw" },
  { name: "TRT World", country: "Turkey", channelId: "UC7fWeaHhqgM4Ry-RMpM2YYw" },
  { name: "NHK World Japan", country: "Japan", channelId: "UCSPEjw8F2nQDtmUKPFNF7_A" },
];

export function embedUrl(channelId: string): string {
  return `https://www.youtube.com/embed/live_stream?channel=${channelId}`;
}

export function countries(): string[] {
  return [...new Set(CHANNELS.map((c) => c.country))].sort();
}
