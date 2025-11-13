import os
import django
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "farajayangu_be.settings.base")  # change this to your settings module
django.setup()

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

print("Storage backend:", default_storage.__class__)

file_name = default_storage.save("test_r2.txt", ContentFile(b"Hello from Cloudflare R2 test!"))
print("Saved as:", file_name)
print("URL:", default_storage.url(file_name))