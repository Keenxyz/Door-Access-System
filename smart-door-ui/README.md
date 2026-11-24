# Smart Door Security UI

This React and TypeScript viewer has its own dependencies and runs separately from the Python recognition program and the existing phone dashboard.

## Run in VS Code on Windows

Open a PowerShell terminal in the repository and run:

```powershell
cd smart-door-ui
npm.cmd ci
npm.cmd run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in a browser. Use Ctrl+C to stop this frontend. To type-check and create the production build, run `npm.cmd run build` from the same folder. Vite writes the build to `smart-door-ui/dist/`.

If PowerShell cannot find npm on this PC, add the Visual Studio Node.js folder for your current terminal, then run the commands above.

```powershell
$env:Path = 'C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Microsoft\VisualStudio\NodeJs;' + $env:Path
npm.cmd --version
```

## Sign in or test with the demo

- Choose **Open demo dashboard** to use sample events and a simulated device. No Supabase authentication is required.
- Use the **paired Supabase viewer** email and password to see real records. Vite reads the public project URL and publishable key from `../dashboard.local.json`. You can also copy `.env.example` to `.env.local`, set both public values, and restart Vite. Use a Supabase publishable key in the frontend. Keep privileged keys and passwords out of these files.
- Supabase Row Level Security limits results to accounts linked in `door_devices`. The viewer reads `door_events`, excluding connection-test records. While a data screen is visible, it checks for new records every 12 seconds. A writer still needs to sync recognition events to Supabase.
- The viewer session is held in memory. Sign in again after reloading the page or after the session expires.

## Browser checks

1. Open the demo and confirm that the overview shows **Demo mode**, recognition activity, and five recent records.
2. Open **Access logs**. Use **Next**, filter to **DENIED**, and search for a name or `UNKNOWN`.
3. Open **Registered users**. Add and remove a demo person, and use search to find a person. The demo roster resets when you leave the demo.
4. Open **Notifications**. Mark an event as read and enable **Unread only**. In live mode, the viewer displays **View visitor photo** for rows with a photo reference. The private image is fetched on demand using the viewer session.
5. Open **Settings**, switch the color theme, and verify the device and account panels. In the browser's mobile device preview, verify that the menu opens, closes, and links to each page.
6. For an end-to-end check, sign in with the paired viewer account, run your normal recognition program, and make one real recognition attempt. Verify the new row in `public.door_events`, then check **Access logs**. Keep that tab visible for the next refresh. The Notifications page should display a new denied event if the attempt was denied.

## Existing integration

The current Supabase schema supports viewer sign-in, writer pairings and access events. Optional visitor photos require the existing alert/photo migration and authorized Storage access. The in-app alerts are based on denied events visible to the viewer. Browser read status and preferences are saved locally per account.

Live enrollment counts and roster entries need a protected backend interface returning names and enrollment dates. Adding and removing people additionally needs authorized enrollment and removal endpoints. Physical lock status and recognizer health need sensor and heartbeat data. The live dashboard therefore shows **UNKNOWN** for physical lock status and **Unknown** for recognition health. A linked writer is an account pairing.

## File map

All paths below are relative to `smart-door-ui/`. Each link opens the complete source.

| File | Purpose and connection |
| --- | --- |
| [package.json](package.json) | Defines the build commands and React, Router, Lucide and TypeScript dependencies. |
| [package-lock.json](package-lock.json) | Pins the dependencies installed by npm ci. |
| [index.html](index.html) | Sets the browser title and loads the React entry point. |
| [vite.config.ts](vite.config.ts) | Reads public connection settings and starts the loopback server on port 5173. |
| [tsconfig.json](tsconfig.json) | Enables TypeScript checks for the Vite configuration and UI source. |
| [.env.example](.env.example) | Lists optional Supabase public settings. |
| [.gitignore](.gitignore) | Excludes installed packages, build output and local configuration. |
| [src/main.tsx](src/main.tsx) | Mounts App with the hash router and loads the two CSS files. |
| [src/App.tsx](src/App.tsx) | Manages the viewer session, demo state, theme, sidebar and routes. |
| [src/pages/Login.tsx](src/pages/Login.tsx) | Handles sign-in and the demo entry point. |
| [src/pages/Dashboard.tsx](src/pages/Dashboard.tsx) | Combines event totals, the activity chart, connection status and recent activity. |
| [src/pages/AccessLogs.tsx](src/pages/AccessLogs.tsx) | Runs name and decision filters and paginates events using AccessTable. |
| [src/pages/RegisteredUsers.tsx](src/pages/RegisteredUsers.tsx) | Manages the demo roster and describes the live enrollment interface needed. |
| [src/pages/Notifications.tsx](src/pages/Notifications.tsx) | Loads recent denied events and tracks locally read alerts. |
| [src/pages/Settings.tsx](src/pages/Settings.tsx) | Shows account and connection information and saves browser preferences. |
| [src/components/Sidebar.tsx](src/components/Sidebar.tsx) | Provides page navigation and sign-out. |
| [src/components/Navbar.tsx](src/components/Navbar.tsx) | Shows the current page, mobile menu button, and data mode. |
| [src/components/StatusCard.tsx](src/components/StatusCard.tsx) | Renders dashboard metrics consistently. |
| [src/components/AccessTable.tsx](src/components/AccessTable.tsx) | Renders event names, decisions, timestamps and scores. |
| [src/components/NotificationCard.tsx](src/components/NotificationCard.tsx) | Shows individual alerts and requests private photos on demand. |
| [src/components/Feedback.tsx](src/components/Feedback.tsx) | Renders loading, errors and retry controls. |
| [src/services/supabase.ts](src/services/supabase.ts) | Handles sign-in and authenticated reads through the existing Auth, Data and Storage APIs. |
| [src/services/useData.ts](src/services/useData.ts) | Handles loading, retry and periodic refresh for data pages. |
| [src/services/demo.ts](src/services/demo.ts) | Supplies isolated demo records and roster entries. |
| [src/services/preferences.ts](src/services/preferences.ts) | Reads and writes browser UI preferences. |
| [src/styles/global.css](src/styles/global.css) | Defines color themes, fonts, forms and the sign-in layout. |
| [src/styles/dashboard.css](src/styles/dashboard.css) | Styles navigation, dashboard cards, tables, charts and mobile layouts. |

