# Generated by Django 4.1.7 on 2024-02-26 05:37

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ddpui", "0049_dbtedge"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="orgdbtmodel",
            name="config",
        ),
    ]
