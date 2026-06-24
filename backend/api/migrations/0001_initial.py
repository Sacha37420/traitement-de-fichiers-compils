import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def seed_actions(apps, schema_editor):
    Action = apps.get_model('api', 'Action')
    actions = [
        # Image
        ('Recadrage',            'Image', "Découper une zone de l'image.",    {'x': 'int', 'y': 'int', 'largeur': 'int', 'hauteur': 'int'}),
        ('Redimensionnement',    'Image', "Modifier la taille de l'image.",   {'largeur': 'int', 'hauteur': 'int', 'mode': 'string'}),
        ('Rotation',             'Image', "Faire pivoter l'image.",           {'angle': 'float'}),
        ('Noir et Blanc',        'Image', "Convertir en niveaux de gris.",    {}),
        ('Sépia',                'Image', "Appliquer un filtre sépia.",       {}),
        ('Contraste',            'Image', "Ajuster le contraste.",            {'niveau': 'float'}),
        ('Luminosité',           'Image', "Ajuster la luminosité.",           {'niveau': 'float'}),
        ('Dessin libre',         'Image', "Annoter avec un tracé libre.",     {'couleur': 'string', 'epaisseur': 'int', 'outil': 'string'}),
        ('Texte',                'Image', "Ajouter du texte sur l'image.",    {'texte': 'string', 'x': 'int', 'y': 'int', 'police': 'string', 'couleur': 'string', 'taille': 'int'}),
        ('Formes',               'Image', "Ajouter des formes géométriques.", {'forme': 'string', 'x': 'int', 'y': 'int', 'couleur': 'string', 'epaisseur': 'int'}),
        ('Calques',              'Image', "Gérer les calques de l'image.",    {'calques': 'array'}),
        ('Stickers',             'Image', "Ajouter un sticker sur l'image.",  {'image': 'string', 'x': 'int', 'y': 'int', 'taille': 'int'}),
        ('Compression',          'Image', "Compresser le fichier image.",     {'qualite': 'int', 'format': 'string'}),
        ('Conversion de format', 'Image', "Convertir le format de l'image.", {'format': 'string'}),
        # Video
        ('Recadrage',            'Video', "Couper une partie de la vidéo.",   {'debut': 'float', 'fin': 'float'}),
        ('Compression',          'Video', "Compresser la vidéo.",             {'qualite': 'int'}),
        ('Conversion de format', 'Video', "Convertir le format vidéo.",       {'format': 'string'}),
        # Audio
        ('Recadrage',            'Audio', "Couper une partie de l'audio.",    {'debut': 'float', 'fin': 'float'}),
        ('Compression',          'Audio', "Compresser l'audio.",              {'qualite': 'int'}),
        ('Conversion de format', 'Audio', "Convertir le format audio.",       {'format': 'string'}),
        # PDF
        ('Rotation',             'PDF',   "Faire pivoter des pages du PDF.",  {'pages': 'string', 'angle': 'int'}),
        ('Compression',          'PDF',   "Compresser le fichier PDF.",       {'qualite': 'int'}),
        ('Conversion de format', 'PDF',   "Convertir le PDF.",                {'format': 'string'}),
    ]
    for nom, type_fichier, description, schema in actions:
        Action.objects.get_or_create(
            nom=nom,
            type_fichier=type_fichier,
            defaults={'description': description, 'parametres_schema': schema},
        )


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Utilisateur',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('email',            models.CharField(max_length=255, unique=True)),
                ('date_inscription', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={'db_table': 'utilisateurs', 'ordering': ['email']},
        ),
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id',  models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('nom', models.CharField(max_length=50, unique=True)),
            ],
            options={'db_table': 'tags', 'ordering': ['nom']},
        ),
        migrations.CreateModel(
            name='Fichier',
            fields=[
                ('id',                models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('nom',               models.CharField(max_length=200)),
                ('type',              models.CharField(max_length=10, choices=[('Image', 'Image'), ('Video', 'Video'), ('Audio', 'Audio'), ('PDF', 'PDF')])),
                ('metadonnees',       models.JSONField(default=dict)),
                ('taille_fichier',    models.DecimalField(decimal_places=3, max_digits=12)),
                ('date_upload',       models.DateTimeField(default=django.utils.timezone.now)),
                ('droits_acces',      models.CharField(default='privé', max_length=10, choices=[('public', 'public'), ('privé', 'privé')])),
                ('fichier_binaire',   models.BinaryField()),
                ('fichier_type_mime', models.CharField(max_length=50)),
                ('utilisateur',       models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='fichiers',
                    to='api.utilisateur',
                )),
                ('tags',              models.ManyToManyField(blank=True, related_name='fichiers', to='api.tag')),
            ],
            options={'db_table': 'fichiers', 'ordering': ['-date_upload']},
        ),
        migrations.CreateModel(
            name='Action',
            fields=[
                ('id',                models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('nom',               models.CharField(max_length=100)),
                ('description',       models.TextField(blank=True)),
                ('type_fichier',      models.CharField(max_length=10, choices=[('Image', 'Image'), ('Video', 'Video'), ('Audio', 'Audio'), ('PDF', 'PDF')])),
                ('parametres_schema', models.JSONField(default=dict)),
            ],
            options={'db_table': 'actions', 'ordering': ['type_fichier', 'nom']},
        ),
        migrations.AddConstraint(
            model_name='action',
            constraint=models.UniqueConstraint(fields=['nom', 'type_fichier'], name='unique_action_nom_type'),
        ),
        migrations.CreateModel(
            name='Modification',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('action',      models.CharField(max_length=100)),
                ('date',        models.DateTimeField(default=django.utils.timezone.now)),
                ('details',     models.JSONField(blank=True, null=True)),
                ('fichier',     models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='modifications',
                    to='api.fichier',
                )),
                ('utilisateur', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='modifications',
                    to='api.utilisateur',
                )),
            ],
            options={'db_table': 'modifications', 'ordering': ['-date']},
        ),
        migrations.CreateModel(
            name='FichierWorkspace',
            fields=[
                ('id',                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('fichier_temporaire_id', models.CharField(max_length=100, unique=True)),
                ('etat',                  models.CharField(default='en_cours', max_length=20)),
                ('nom_temporaire',        models.CharField(blank=True, max_length=200, null=True)),
                ('historique_local',      models.JSONField(blank=True, default=list, null=True)),
                ('fichier_source',        models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='workspace_items',
                    to='api.fichier',
                )),
                ('tags_temporaires',      models.ManyToManyField(blank=True, related_name='fichiers_workspace', to='api.tag')),
            ],
            options={'db_table': 'fichiers_workspace'},
        ),
        migrations.RunPython(seed_actions, migrations.RunPython.noop),
    ]
