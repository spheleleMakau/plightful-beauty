# Plightful Beauty Salon Management & Booking System

Plightful is a Django application for a beauty salon. It provides a public website, appointment booking, worker dashboards, walk-in tracking, client and service management, owner analytics, CSV reports, and Django admin support.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

Open `http://127.0.0.1:8000/` after starting the development server.

## Deploy to Render

This repository includes `render.yaml` for a Render web service and PostgreSQL database. In Render, choose **New > Blueprint**, connect this repository, and apply the blueprint. Render will install dependencies, collect static files, run migrations, and start Gunicorn automatically.

If the service was created manually, set its **Start Command** to `gunicorn plightful.wsgi:application --bind 0.0.0.0:$PORT`. Do not use `gunicorn app:app`; that is not a Django module in this project.

After the first deploy, create an owner account from the Render shell:

```bash
python manage.py createsuperuser
```

The blueprint sets `DEBUG=False`, generates a `SECRET_KEY`, and connects the app to the managed PostgreSQL database. Uploaded media files remain local to the web service filesystem; use object storage for persistent production uploads if clients will upload inspiration images.

The project uses SQLite by default. Settings are loaded from environment variables with `python-dotenv`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | `replace-me` | Django secret key |
| `DEBUG` | `True` | Enables development behavior and media serving |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |

## URL Map

| URL | Function | Purpose |
| --- | --- | --- |
| `/` | `home` | Public home page |
| `/website/` | `home` | Public home page alias |
| `/about/` | `about` | About page |
| `/services/` | `services` | Lists active services |
| `/gallery/` | `gallery` | Gallery page |
| `/contact/` | `contact` | Contact page |
| `/book/` | `book` | Create an appointment request |
| `/booked-times/` | `booked_times` | JSON list of booked times for a date |
| `/worker/login/` | `WorkerLoginView` | Active worker login |
| `/dashboard/` | `dashboard` | Customer, worker, or owner dashboard |
| `/owner/` | `owner_dashboard` | Owner analytics dashboard |
| `/owner/preview/` | `owner_preview` | Debug-only empty dashboard preview |
| `/owner/appointments/` | `appointment_list` | Filter and search appointments |
| `/owner/appointments/<id>/` | `appointment_manage` | Assign, update, or add notes to an appointment |
| `/owner/clients/` | `client_list` | Search clients |
| `/owner/clients/new/` | `client_edit` | Create a client |
| `/owner/clients/<id>/` | `client_detail` | View a client and their records |
| `/owner/clients/<id>/edit/` | `client_edit` | Edit a client |
| `/owner/workers/` | `worker_list` | List workers |
| `/owner/workers/<id>/` | `worker_detail` | View worker activity and revenue |
| `/owner/workers/new/` | `worker_create` | Create a worker account |
| `/owner/workers/<id>/toggle/` | `worker_toggle` | Activate or deactivate a worker |
| `/owner/services/new/` | `service_manage` | Create a service |
| `/owner/services/<id>/edit/` | `service_manage` | Edit a service |
| `/walk-ins/new/` | `walk_in_create` | Record a walk-in client visit |
| `/reports.csv` | `report_csv` | Download the selected owner report as CSV |
| `/admin/` | Django admin | Manage all registered models |

There is intentionally no owner login URL. Owners use a Django-authenticated account, normally created with `createsuperuser` or through the admin. The worker login form is restricted to active worker profiles.

## Functions and Classes

The application logic is in the `core` Django app. The sections below document every application function and method, excluding generated migration methods and standard `AppConfig` boilerplate.

### `core.models`

#### `SiteSettings`

- `__str__()`: Returns the configured salon name.

#### `Profile`

- `__str__()`: Returns the user's full name or username followed by the displayed role.
- `create_user_profile(sender, instance, created, **kwargs)`: A `post_save` signal receiver that creates a profile for every new Django user. New superusers become owners; other users default to customers.

#### `Worker`

- `__str__()`: Returns the worker's full name or username.

#### `Client`

- `visits_count`: Returns the number of related `ClientVisit` records.
- `total_spent`: Returns the sum of visit amounts, or `0` when the client has no visits.
- `is_loyal`: Returns `True` after at least three visits.
- `__str__()`: Returns the client's full name.

#### `Service`

- `__str__()`: Returns the service name.

#### `Appointment`

- `clean()`: Rejects appointments in the past. It also rejects a reserved unassigned time slot, while allowing cancelled appointments to be ignored.
- `__str__()`: Returns the client, service, and appointment date.

#### `WalkIn`

- `clean()`: Rejects negative amounts and satisfaction scores outside the range 1 to 5.
- `time_spent_minutes`: Calculates the number of minutes since `start_time`.
- `time_spent_display`: Formats elapsed time as `2h 15m`, or returns `Not started` when no start time exists.
- `__str__()`: Returns the client name followed by `walk-in`.

#### `Review`

- `clean()`: Ensures a review rating is between 1 and 5.

### `core.forms`

- `OwnerLoginForm.confirm_login_allowed(user)`: Allows only users whose profile role is `owner`.
- `WorkerLoginForm.confirm_login_allowed(user)`: Allows only users with an active worker profile and the `worker` role.
- `BookingForm.__init__(*args, **kwargs)`: Limits services to active services and prevents selecting a date before today.
- `BookingForm.clean()`: Validates future dates and times and prevents double booking, including bookings made by another user while the form is open.
- `BookingForm.save(commit=True)`: Finds or creates a client by phone or email, updates their contact details, and creates the appointment.
- `WalkInForm.save(commit=True)`: Finds or creates a client by phone, updates the name, and creates the walk-in record.
- `AppointmentManageForm.__init__(*args, **kwargs)`: Limits assignable workers to active workers.
- `WorkerCreateForm.clean_username()`: Rejects usernames that already exist.
- `WorkerCreateForm.save()`: Creates a Django user, sets the worker profile role and phone number, and creates the related worker record.

`ClientManageForm` and `ServiceManageForm` are model forms for editing clients and services. Their `Meta` definitions specify the fields exposed by the owner forms.

### `core.analytics`

- `business_summary(start_date, end_date)`: Accepts `date` objects or ISO date strings and returns appointment counts, walk-in counts, completed appointments, combined revenue, unique clients served, average walk-in satisfaction, and the five most popular completed services. Cancelled appointments are excluded.

### `core.views`

- `owner_required(view_func)`: Decorator that requires login and an owner profile; otherwise it raises `PermissionDenied`.
- `selected_period(request)`: Reads `period=week`, `period=month`, or valid `start` and `end` query parameters. Defaults to today.
- `home(request)`: Renders the public home page.
- `about(request)`: Renders the about page.
- `services(request)`: Renders active services.
- `gallery(request)`: Renders the gallery page.
- `contact(request)`: Renders the contact page.
- `OwnerLoginView.get_success_url()`: Redirects an authenticated owner to the requested page or `/owner/`.
- `WorkerLoginView.get_success_url()`: Redirects an authenticated worker to the requested page or `/dashboard/`.
- `book(request)`: Displays the booking form, remembers customer contact details in the session, accepts up to two inspiration images, and renders a confirmation after saving.
- `booked_times(request)`: Returns non-cancelled appointment times for the requested `date` as JSON.
- `dashboard(request)`: Selects the correct dashboard for customers, workers, staff, and owners. Worker context includes today's appointments, assigned clients, completed count, revenue, upcoming count, and recent history.
- `owner_dashboard(request)`: Builds period-based business analytics, appointment and walk-in lists, worker performance, loyalty counts, average ticket, and satisfaction data.
- `owner_preview(request)`: Renders an empty owner dashboard preview only while `DEBUG=True`.
- `appointment_list(request)`: Lists appointments with optional status filtering and client name or phone search.
- `appointment_manage(request, pk)`: Assigns a worker and updates status or notes for one appointment.
- `client_list(request)`: Lists clients with visit counts and optional name, phone, or email search.
- `client_detail(request, pk)`: Displays a client and their appointments, walk-ins, and visits.
- `client_edit(request, pk=None)`: Creates a client when `pk` is absent or edits the selected client.
- `service_manage(request, pk=None)`: Creates a service when `pk` is absent or edits the selected service.
- `worker_list(request)`: Lists workers with appointment totals.
- `worker_detail(request, pk)`: Shows daily and month-to-date worker appointments, walk-ins, clients served, completed services, and revenue.
- `worker_create(request)`: Validates and creates a worker account from `WorkerCreateForm`.
- `worker_toggle(request, pk)`: Toggles both the worker record and linked user between active and inactive.
- `walk_in_create(request)`: Allows staff, owners, and workers to record a walk-in visit.
- `report_csv(request)`: Exports `business_summary()` for the selected period as a downloadable CSV file.

### `core.admin`

- `WalkInAdmin.time_inside(obj)`: Displays a walk-in's formatted elapsed time using `WalkIn.time_spent_display`.

### Management and project entry points

- `core.management.commands.seed_demo.Command.handle(*args, **options)`: Creates development services, one demo worker, and two demo clients. The demo worker password is `demo-password-change-me` and must not be used in a shared environment.
- `manage.main()`: Sets `DJANGO_SETTINGS_MODULE` to `plightful.settings` and forwards command-line arguments to Django.

## Data Models

- `SiteSettings`: Salon name and contact details.
- `Profile`: One-to-one user role and phone information (`owner`, `worker`, or `customer`).
- `Worker`: Worker account, position, phone, active state, and join date.
- `Client`: Customer identity and contact details.
- `Service`: Service description, duration, price, and active state.
- `Appointment`: Scheduled service, client, optional worker, status, notes, and inspiration images.
- `WalkIn`: Unscheduled service visit, amount, worker, style details, satisfaction, and start time.
- `ClientVisit`: Historical visit and amount used for client statistics.
- `Review`: Client rating and optional appointment comment.

## Development and Tests

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
python manage.py test
python manage.py collectstatic
```

The tests in `core/tests.py` cover booking creation, double-booking prevention, walk-in duration, authentication, role access, image uploads, revenue summaries, worker hiring, worker dashboards, owner analytics, and superuser access.

For production, set `DEBUG=False`, use a strong `SECRET_KEY`, configure `ALLOWED_HOSTS`, move the database to PostgreSQL, run `collectstatic`, and serve the project behind Gunicorn and a reverse proxy.
