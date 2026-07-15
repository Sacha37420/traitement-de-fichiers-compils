import {
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
  signal,
} from '@angular/core';
import { WorkFile } from '../../core/work-file.model';
import { getPdfPageCount, renderPdfThumbnail } from '../../core/pdf.util';

interface PageThumb { index: number; thumb: string; }

/** Gestionnaire de pages PDF : miniatures, réordonnancement et suppression. */
@Component({
  selector: 'app-pdf-page-manager',
  standalone: true,
  templateUrl: './pdf-page-manager.html',
  styleUrl: './pdf-page-manager.scss',
})
export class PdfPageManagerComponent implements OnInit {
  @Input({ required: true }) file!: WorkFile;
  @Output() confirmed = new EventEmitter<number[]>();
  @Output() cancelled = new EventEmitter<void>();

  pages = signal<PageThumb[]>([]);
  loading = signal(true);
  error = signal('');

  async ngOnInit(): Promise<void> {
    try {
      const count = await getPdfPageCount(this.file.blob);
      const list: PageThumb[] = [];
      for (let i = 1; i <= count; i++) {
        list.push({ index: i - 1, thumb: await renderPdfThumbnail(this.file.blob, i, 150) });
        this.pages.set([...list]);
      }
    } catch {
      this.error.set('Impossible de lire ce PDF.');
    } finally {
      this.loading.set(false);
    }
  }

  move(pos: number, dir: -1 | 1): void {
    const list = [...this.pages()];
    const target = pos + dir;
    if (target < 0 || target >= list.length) return;
    [list[pos], list[target]] = [list[target], list[pos]];
    this.pages.set(list);
  }

  remove(pos: number): void {
    this.pages.set(this.pages().filter((_, i) => i !== pos));
  }

  apply(): void {
    this.confirmed.emit(this.pages().map((p) => p.index));
  }
}
