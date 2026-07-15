import { Component } from '@angular/core';
import { NavbarComponent } from '../../shared/navbar/navbar';
import { FileWorkbenchComponent } from '../../shared/file-workbench/file-workbench';

@Component({
  selector: 'app-atelier',
  standalone: true,
  imports: [NavbarComponent, FileWorkbenchComponent],
  templateUrl: './atelier.html',
  styleUrl: './atelier.scss',
})
export class AtelierComponent {}
