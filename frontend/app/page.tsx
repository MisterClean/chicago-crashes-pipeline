import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-900 dark:to-gray-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24">
        <div className="text-center">
          <h1 className="text-4xl font-bold tracking-tight text-gray-900 dark:text-white sm:text-5xl md:text-6xl">
            Chicago Crash Dashboard
          </h1>
          <p className="mt-6 max-w-2xl mx-auto text-xl text-gray-600 dark:text-gray-300">
            Explore traffic crash data across Chicago. Understand patterns,
            identify dangerous intersections, and advocate for safer streets.
          </p>
          <div className="mt-10 flex justify-center gap-4">
            <Link
              href="/dashboard"
              className="rounded-md bg-chicago-red px-6 py-3 text-lg font-semibold text-white shadow-sm hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600"
            >
              View Dashboard
            </Link>
            <a
              href="https://github.com/lakeview-urbanists/chicago-crash-dashboard"
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md bg-gray-100 dark:bg-gray-700 px-6 py-3 text-lg font-semibold text-gray-900 dark:text-white shadow-sm hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              GitHub
            </a>
          </div>
        </div>

        <div className="mt-24 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-3">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              800K+ Crash Records
            </h3>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Comprehensive data from the Chicago Open Data Portal, updated
              regularly with the latest crash reports.
            </p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Interactive Maps
            </h3>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Visualize crashes on an interactive map. Filter by date, severity,
              and crash type to find patterns.
            </p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Trend Analysis
            </h3>
            <p className="mt-2 text-gray-600 dark:text-gray-400">
              Track crash trends over time. See how safety is changing in your
              neighborhood.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
