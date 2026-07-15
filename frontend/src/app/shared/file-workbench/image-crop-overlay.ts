import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  ViewChild,
  signal,
} from '@angular/core';
import { WorkFile } from '../../core/work-file.model';
import { Rect } from '../../core/image-canvas.util';

interface DispRect { x: number; y: number; w: number; h: number; }

/** Overlay de recadrage : rectangle déplaçable + poignée de redimensionnement (SE). */
@Component({
  selector: 'app-image-crop-overlay',
  standalone: true,
  templateUrl: './image-crop-overlay.html',
  styleUrl: './image-crop-overlay.scss',
})
export class ImageCropOverlayComponent {
  @Input({ required: true }) file!: WorkFile;
  @Output() confirmed = new EventEmitter<Rect>();
  @Output() cancelled = new EventEmitter<void>();

  @ViewChild('wrap') wrap!: ElementRef<HTMLDivElement>;

  rect = signal<DispRect>({ x: 0, y: 0, w: 0, h: 0 });

  private natW = 0;
  private natH = 0;
  private dispW = 0;
  private dispH = 0;
  private mode: 'none' | 'move' | 'resize' = 'none';
  private startPx = 0;
  private startPy = 0;
  private startRect: DispRect = { x: 0, y: 0, w: 0, h: 0 };

  onImgLoad(img: HTMLImageElement): void {
    this.natW = img.naturalWidth;
    this.natH = img.naturalHeight;
    this.dispW = img.clientWidth;
    this.dispH = img.clientHeight;
    const w = this.dispW * 0.8;
    const h = this.dispH * 0.8;
    this.rect.set({ x: (this.dispW - w) / 2, y: (this.dispH - h) / 2, w, h });
  }

  startMove(ev: PointerEvent): void {
    this.begin('move', ev);
  }

  startResize(ev: PointerEvent): void {
    ev.stopPropagation();
    this.begin('resize', ev);
  }

  private begin(mode: 'move' | 'resize', ev: PointerEvent): void {
    ev.preventDefault();
    this.mode = mode;
    this.startPx = ev.clientX;
    this.startPy = ev.clientY;
    this.startRect = { ...this.rect() };
  }

  onMove(ev: PointerEvent): void {
    if (this.mode === 'none') return;
    ev.preventDefault();
    const dx = ev.clientX - this.startPx;
    const dy = ev.clientY - this.startPy;
    const r = { ...this.startRect };
    if (this.mode === 'move') {
      r.x = clamp(r.x + dx, 0, this.dispW - r.w);
      r.y = clamp(r.y + dy, 0, this.dispH - r.h);
    } else {
      r.w = clamp(r.w + dx, 16, this.dispW - r.x);
      r.h = clamp(r.h + dy, 16, this.dispH - r.y);
    }
    this.rect.set(r);
  }

  end(): void {
    this.mode = 'none';
  }

  apply(): void {
    const r = this.rect();
    if (r.w < 1 || r.h < 1 || this.dispW === 0 || this.dispH === 0) {
      this.cancelled.emit();
      return;
    }
    const sx = this.natW / this.dispW;
    const sy = this.natH / this.dispH;
    this.confirmed.emit({ x: r.x * sx, y: r.y * sy, width: r.w * sx, height: r.h * sy });
  }
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), Math.max(min, max));
}
