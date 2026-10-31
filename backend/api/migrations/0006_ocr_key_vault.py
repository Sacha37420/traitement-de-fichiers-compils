import api.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_fichier_partage_storage'),
    ]

    # Une table neuve seulement : le coffre de la clé d'API Mistral (OCR).
    operations = [
        migrations.CreateModel(
            name='OcrKeyVault',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner_email', models.EmailField(max_length=255, unique=True)),
                ('mistral_key', api.fields.EncryptedTextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'ocr_key_vault',
            },
        ),
    ]
