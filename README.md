# farajayangu_be

A Django REST Framework project built with **NTC (Nexent Toolkit Console)** structure for scalable, maintainable API development.

---

## 📋 Project Description

<!-- Add your project-specific description here -->
*This section is for you to describe what your project does, its main features, and business purpose.*

---

## 🏗️ Architecture Overview

This project follows the **NTC structure** with enterprise-grade patterns:

- **API-First Design**: RESTful APIs with standardized JSON responses
- **Modular Apps**: Feature-based Django applications in `apps/` directory
- **Service/Selector Pattern**: Clean separation of business logic and data access
- **JWT Authentication**: Secure token-based authentication with refresh tokens
- **Background Tasks**: Celery integration for async processing
- **Cloud Ready**: Docker containerization and deployment configurations

## 📁 Project Structure

```
farajayangu_be/
├── .env                    # Environment variables
├── .knowledge/             # AI documentation for project understanding
├── manage.py              # Django management script
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # Local development environment
├── farajayangu_be/        # Django project configuration
│   ├── settings/          # Split settings (dev/prod)
│   ├── urls.py           # Main URL routing
│   └── management/       # Custom management commands
├── apps/                 # Django applications
│   ├── common/           # Shared utilities and base models
│   └── [your_apps]/      # Feature-specific apps
└── core/                 # Framework utilities and extensions
    ├── response_wrapper.py  # Standardized API responses
    ├── pagination.py       # DRF pagination classes
    └── services/           # External service integrations
```

## 🚀 Quick Start

### 1. Environment Setup
```bash
# Clone and navigate to project
cd farajayangu_be

# Create virtual environment
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Database Setup
```bash
# Run migrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser
```

### 3. Run Development Server
```bash
python manage.py runserver
```

The API will be available at:
- **API Base**: http://127.0.0.1:8000/
- **Admin Panel**: http://127.0.0.1:8000/admin/
- **API Documentation**: http://127.0.0.1:8000/docs/

## 🛠️ Development Commands

### App Management
```bash
# Create new app with NTC structure
python manage.py create_app app_name

# Alternative: Use NTC CLI (if installed globally)
ntc create app app_name
```

### Database Operations
```bash
# Create migrations
python manage.py makemigrations [app_name]

# Apply migrations
python manage.py migrate

# Reset database (development only)
python manage.py flush
```

### Development Tools
```bash
# Run tests
python manage.py test

# Collect static files (production)
python manage.py collectstatic

# Django shell
python manage.py shell
```

## 🏛️ Development Patterns

### API Response Format
All endpoints return standardized responses:

```json
{
  "status": "success|error",
  "message": "Human-readable message",
  "data": { /* Response data */ }
}
```

### Service/Selector Pattern
```python
# Business logic in services/
from apps.myapp.services.user_service import create_user

# Data queries in selectors/
from apps.myapp.selectors.user_selector import get_active_users

# Views handle HTTP only
@api_view(['POST'])
def create_user_view(request):
    user = create_user(request.data)
    return success_response(data=user, message="User created")
```

### Model Inheritance
```python
# Use TimeStampedModel for automatic timestamps
from apps.common.models import TimeStampedModel

class MyModel(TimeStampedModel):
    name = models.CharField(max_length=100)
    # created_at and updated_at added automatically
```

## 🔧 Configuration

### Environment Variables
Copy `.env.example` to `.env` and configure:

```env
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///db.sqlite3
REDIS_URL=redis://localhost:6379
```

### Settings Structure
- `settings/base.py` - Shared settings
- `settings/dev.py` - Development settings
- `settings/prod.py` - Production settings

## 🐳 Docker Development

### Local Development
```bash
# Start all services
docker-compose up

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Production Build
```bash
# Build production image
docker build -t farajayangu_be .

# Run production container
docker run -p 8000:8000 farajayangu_be
```

## 📚 API Documentation

### Interactive Documentation
- **Swagger UI**: http://127.0.0.1:8000/docs/
- **OpenAPI Schema**: http://127.0.0.1:8000/schema/

### Authentication
```bash
# Get JWT tokens
POST /auth/login/
{
  "email": "user@example.com",
  "password": "password"
}

# Use access token in headers
Authorization: Bearer <access_token>

# Refresh token
POST /auth/refresh/
{
  "refresh": "<refresh_token>"
}
```

## 🧪 Testing

### Run Tests
```bash
# All tests
python manage.py test

# Specific app
python manage.py test apps.myapp

# With coverage
coverage run --source='.' manage.py test
coverage report
```

### Test Structure
```
apps/myapp/tests/
├── __init__.py
├── test_models.py
├── test_services.py
├── test_selectors.py
└── test_views.py
```

## 📦 Deployment

### Environment Setup
1. Set `DEBUG=False` in production
2. Configure production database
3. Set up Redis for caching
4. Configure email settings
5. Set up Celery workers

### CapRover Deployment
```bash
# Deploy to CapRover
caprover deploy

# Or use captain-definition for auto-deployment
git push caprover main
```

## 🔍 Troubleshooting

### Common Issues

**Migration Errors**:
```bash
# Reset migrations (development only)
python manage.py migrate --fake-initial
```

**Import Errors**:
- Ensure virtual environment is activated
- Check `PYTHONPATH` includes project root
- Verify app is in `INSTALLED_APPS`

**Permission Errors**:
- Check JWT token is valid
- Verify user has required permissions
- Ensure proper authentication headers

## 📖 Additional Resources

- **NTC Documentation**: [Link to NTC docs]
- **Django REST Framework**: https://www.django-rest-framework.org/
- **Django Documentation**: https://docs.djangoproject.com/
- **Project Knowledge Base**: See `.knowledge/` directory for AI-friendly documentation

## 🤝 Contributing

<!-- Add your contribution guidelines here -->
*This section is for your team's contribution guidelines, coding standards, and development workflow.*

---

## 📄 License

<!-- Add your license information here -->
*Add your project's license information.*

---

**Generated by NTC (Nexent Toolkit Console)** - A tool for creating production-ready Django REST Framework projects with best practices built-in.

