# How to Run the Transpo-Sort Flask App

I have converted your project into a Flask web application.

## Quick Start

1.  Open the folder `c:\Users\boris\Downloads\Transpo-sort-main\Transpo-sort-main` in File Explorer.
2.  Double-click `run_flask.bat`.
3.  This will:
    -   Install all necessary Python dependencies (including Flask).
    -   Start the web server.
4.  Open your browser and go to `http://127.0.0.1:5000`.

## Manual Setup

If you prefer to run it manually from the terminal:

1.  Open a terminal in `c:\Users\boris\Downloads\Transpo-sort-main\Transpo-sort-main`.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Run the app:
    ```bash
    python web_app.py
    ```

## Functionality

-   **Landing Page**: Shows a "Run Optimization" button.
-   **Optimization**: When clicked, it runs the `generate_synthetic_neighborhood`, `place_new_stops`, and `build_map` functions.
-   **Result**: Displays the generated map directly in the browser.
