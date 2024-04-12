# Generated by Django 4.1.7 on 2024-04-05 05:20

from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("ddpui", "0064_orguser_new_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="role",
            name="level",
            field=models.SmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="permission",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="role",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]