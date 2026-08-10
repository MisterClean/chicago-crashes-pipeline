import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Chicago Crash Dashboard",
  description:
    "Public dashboard visualizing Chicago traffic crash data. Explore patterns, trends, and safety insights across Chicago neighborhoods.",
  openGraph: {
    title: "Chicago Crash Dashboard",
    description: "Visualizing traffic safety data for Chicago",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <header className="bg-gray-900 text-white">
          <nav className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center">
                <Link href="/" className="text-xl font-bold">
                  Chicago Crash Dashboard
                </Link>
              </div>
              <div className="flex items-center space-x-4">
                <Link
                  href="/dashboard"
                  className="text-gray-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium"
                >
                  Dashboard
                </Link>
                <Link
                  href="/dashboard/location-report"
                  className="text-gray-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium"
                >
                  Location Report
                </Link>
                <Link
                  href="/dashboard/ward-scorecard"
                  className="text-gray-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium"
                >
                  Ward Scorecard
                </Link>
              </div>
            </div>
          </nav>
        </header>
        <main>{children}</main>
        <footer className="bg-gray-100 dark:bg-gray-900 py-8 mt-auto">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-sm text-gray-600 dark:text-gray-400">
            <p>
              Data from{" "}
              <a
                href="https://data.cityofchicago.org"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-gray-900 dark:hover:text-gray-200"
              >
                Chicago Open Data Portal
              </a>
              .{" "}
              <a
                href="https://github.com/MisterClean/chicago-crashes-pipeline"
                target="_blank"
                rel="noopener noreferrer"
                className="underline hover:text-gray-900 dark:hover:text-gray-200"
              >
                Open Source on GitHub
              </a>
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
