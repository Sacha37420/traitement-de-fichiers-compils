import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { FichierService, Fichier } from '../../core/fichier.service';
import { WorkspaceService } from '../../core/workspace.service';
import { NavbarComponent } from '../../shared/navbar/navbar';

@Component({
  selector: 'app-upload-fichier',
  standalone: true,
  imports: [CommonModule, FormsModule, NavbarComponent],
  templateUrl: './upload-fichier.html',
  styleUrl: './upload-fichier.scss',
})
export class UploadFichierComponent {
  private fichierService = inject(FichierService);
  private workspaceService = inject(WorkspaceService);
  private router = inject(Router);

  nom = '';
  type: string = 'Image';
  tagsInput = '';
  selectedFile: File | null = null;
  uploading = false;
  error = '';
  success = '';
  uploadedFichier: Fichier | null = null;

  readonly typeOptions = ['Image', 'Video', 'Audio', 'PDF'];

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) {
      this.selectedFile = input.files[0];
      if (!this.nom) {
        this.nom = this.selectedFile.name.replace(/\.[^.]+$/, '');
      }
      this.type = this.detectType(this.selectedFile.type);
    }
  }

  private detectType(mime: string): string {
    if (mime.startsWith('image/')) return 'Image';
    if (mime.startsWith('video/')) return 'Video';
    if (mime.startsWith('audio/')) return 'Audio';
    if (mime === 'application/pdf') return 'PDF';
    return this.type;
  }

  upload(): void {
    if (!this.selectedFile || !this.nom || !this.type) {
      this.error = 'Veuillez remplir tous les champs obligatoires.';
      return;
    }

    this.uploading = true;
    this.error = '';
    this.success = '';

    const formData = new FormData();
    formData.append('fichier', this.selectedFile);
    formData.append('nom', this.nom);
    formData.append('type', this.type);
    const tags = this.tagsInput.split(',').map(t => t.trim()).filter(Boolean);
    tags.forEach(t => formData.append('tags', t));

    this.fichierService.uploadFichier(formData).subscribe({
      next: (fichier) => {
        this.uploadedFichier = fichier;
        this.success = `Fichier "${fichier.nom}" uploadé avec succès (${fichier.taille_fichier} Mo).`;
        this.uploading = false;
      },
      error: (err) => {
        this.error = err.error?.error || 'Erreur lors de l\'upload.';
        this.uploading = false;
      },
    });
  }

  addToWorkspaceAndEdit(): void {
    if (!this.uploadedFichier) return;
    this.workspaceService.addFichierToWorkspace(this.uploadedFichier.id).subscribe({
      next: () => this.router.navigate(['/editeur', this.uploadedFichier!.type, this.uploadedFichier!.id]),
      error: () => this.router.navigate(['/editeur', this.uploadedFichier!.type, this.uploadedFichier!.id]),
    });
  }

  reset(): void {
    this.nom = '';
    this.type = 'Image';
    this.tagsInput = '';
    this.selectedFile = null;
    this.uploadedFichier = null;
    this.success = '';
    this.error = '';
  }
}
