# Installation

## Requirements

- Python >= 3.12
- Django >= 6.1

## Installing the package

```bash
pip install django-workflow-kit
```

### Optional extras

Optional integrations are installed as separate extras:

```bash
pip install django-workflow-kit[drf]    # Django REST Framework support
pip install django-workflow-kit[celery] # Celery task integration
pip install django-workflow-kit[redis]  # Redis-backed features
```

## Configuring a Django project

1. Add `workflow_kit` to your `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       ...
       "workflow_kit",
   ]
   ```

2. Run migrations:

   ```bash
   python manage.py migrate
   ```

3. (Optional) Configure the `WORKFLOW_KIT` settings dict. See
   [Configuration](concepts/configuration.md).

Basic usage requires no configuration at all.

## Development installation

```bash
git clone https://github.com/anomalyco/django-workflow-kit.git
cd django-workflow-kit
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```