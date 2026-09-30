// Thin globe.gl wrapper: events as colored 3D columns by lat/lon —
// altitude from |signal_score|, color from verdict, click → select.

import Globe, { type GlobeInstance } from "globe.gl";
import type { EventOut } from "../api";
import { type GlobePoint, toPoints } from "./points";

export class GlobeView {
  private globe: GlobeInstance;

  constructor(container: HTMLElement, onSelect: (e: EventOut) => void) {
    this.globe = new Globe(container)
      .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-dark.jpg")
      .backgroundColor("#0b0e14")
      .pointLat("lat")
      .pointLng("lng")
      .pointColor("color")
      // points render as 3D columns: altitude IS the bar height
      .pointAltitude("size")
      .pointRadius(0.45)
      .pointLabel("label")
      .onPointClick((p: object) => onSelect((p as GlobePoint).event));

    const controls = this.globe.controls() as { autoRotate: boolean; autoRotateSpeed: number };
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.4;
  }

  setEvents(events: EventOut[]): void {
    this.globe.pointsData(toPoints(events));
  }

  resize(w: number, h: number): void {
    this.globe.width(w).height(h);
  }
}
