# My Ride K-12 Home Assistant Integration

A custom Home Assistant integration for **My Ride K-12** (by Tyler Technologies) that allows tracking school buses in real-time and bringing student route, schedule, and stop information into your Home Assistant instance.

This integration has been reverse-engineered from the My Ride K-12 API and authentication flows.

---

## Features

* **Real-time Bus tracking (`device_tracker`):** Shows the live location, heading, speed, and last reporting time of the active school bus assigned to your student's routes. Plot them directly on your Home Assistant Map cards.
* **Student Route Sensors (`sensor`):** 
  * **Next Bus Stop:** Reports the name of the next scheduled stop, along with attributes for planned arrival time, actual arrival time, eta, and bus number.
  * **Bus Status:** Reports status (e.g., *On Time*, *Late*, *Early*, *Completed*, *Not Active*) and attributes like the driver's name.
* **Dynamic Polling:** Uses a smart update coordinator that polls bus locations every **30 seconds** only when a route is scheduled to run today and the current time is active. Otherwise, it scales back to **15 minutes** (passive mode) to prevent API rate-limiting or account lockout.
* **Self-Healing Auth:** Keeps credentials secure and handles AWS Cognito session tokens in-memory. Automatically triggers re-login and retrieves fresh Cognito access/refresh tokens in the background when sessions expire.

---

## Installation

### Method 1: HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots `...` in the top right corner and select **Custom repositories**.
3. Paste the URL of this repository: `https://git.52203.net/jrittenh/ha-myride` (or your public git mirror).
4. Select **Integration** as the Category and click **Add**.
5. Once added, click **Download** on the My Ride K-12 integration card.
6. **Restart Home Assistant** to load the integration.

### Method 2: Manual

1. Download the repository source code zip file.
2. Extract and copy the `custom_components/myride` folder into your Home Assistant directory under `config/custom_components/`.
   The final path should look like: `config/custom_components/myride/manifest.json`.
3. **Restart Home Assistant** to load the integration.

---

## Configuration

1. In Home Assistant, navigate to **Settings** -> **Devices & Services**.
2. Click **Add Integration** in the bottom right corner.
3. Search for **My Ride K-12** and select it.
4. Enter your login credentials (the same Email and Password used in the mobile app / website).
5. If your account is associated with multiple school districts (tenants), you will be presented with a dropdown list to choose which district to track.
6. Click submit to complete setup. Your students, sensors, and bus trackers will be automatically discovered.

---

## Security & Privacy

* **100% Local Execution:** All network communication goes directly from your local Home Assistant instance to the official Tyler Tech endpoints (`https://myridek12.tylerapi.com` and Cognito). No intermediate servers, proxies, or analytics trackers are used.
* **Secure Storage:** Your login credentials are encrypted and stored in Home Assistant's secure storage. Authentication tokens are held in-memory and never written to disk.
* **Log Sanitization:** Sensitive private data (e.g., student names, home addresses, coordinates, and Cognito Bearer headers) are filtered and never logged to `homeassistant.log`, even when debug logging is active.

---

## Development

This project uses `uv` for python virtualenv and package management.

### Run Tests locally

Install dev dependencies and run the `pytest` test suite:
```bash
uv run pytest
```

### CI/CD

Forgejo Actions CI configurations are located in `.forgejo/workflows/ci.yml` and execute automatically on pushes/PRs to the `main` branch to run the test suite.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
