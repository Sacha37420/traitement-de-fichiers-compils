import { Component } from '@angular/core';
import { FileWorkbenchComponent } from '../../shared/file-workbench/file-workbench';

@Component({
  selector: 'app-atelier',
  standalone: true,
  imports: [FileWorkbenchComponent],
  templateUrl: './atelier.html',
  styleUrl: './atelier.scss',
})
export class AtelierComponent {}
