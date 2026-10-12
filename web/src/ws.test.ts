import { describe, expect, it, vi } from "vite-plus/test";
import { RealtimeClient, type WSMessage } from "./ws";

// Minimal fake WebSocket driven manually.
class FakeWS {
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(public url: string) {}
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(msg: WSMessage) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  send(s: string) {
    this.sent.push(s);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

describe("RealtimeClient", () => {
  it("backoff grows and caps at 15s", () => {
    const rt = new RealtimeClient(
      "ws://x",
      () => {},
      () => {},
    );
    expect(rt.backoffMs(0)).toBeGreaterThanOrEqual(400);
    expect(rt.backoffMs(0)).toBeLessThanOrEqual(600);
    expect(rt.backoffMs(20)).toBeLessThanOrEqual(15_000 * 1.2);
  });

  it("reports status and forwards parsed messages", () => {
    let last: FakeWS | null = null;
    const statuses: string[] = [];
    const msgs: WSMessage[] = [];
    const rt = new RealtimeClient(
      "ws://x",
      (m) => msgs.push(m),
      (s) => statuses.push(s),
      (u) => ((last = new FakeWS(u)), last) as unknown as WebSocket,
    );
    rt.connect();
    expect(statuses).toContain("connecting");
    last!.open();
    expect(statuses).toContain("open");
    last!.emit({ type: "new_events", events: [] });
    expect(msgs.at(-1)?.type).toBe("new_events");
    rt.close();
  });

  it("schedules a reconnect on close", () => {
    vi.useFakeTimers();
    const factories: FakeWS[] = [];
    const rt = new RealtimeClient(
      "ws://x",
      () => {},
      () => {},
      (u) => {
        const w = new FakeWS(u);
        factories.push(w);
        return w as unknown as WebSocket;
      },
    );
    rt.connect();
    factories[0].open();
    factories[0].close(); // drop → should schedule a reconnect
    vi.advanceTimersByTime(20_000);
    expect(factories.length).toBeGreaterThan(1);
    rt.close();
    vi.useRealTimers();
  });
});
