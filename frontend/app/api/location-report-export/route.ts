import { NextRequest, NextResponse } from "next/server";

const ABSOLUTE_URL_PATTERN = /^https?:\/\//i;
const API_KEY_HEADER = "X-API-Key";

function isAbsoluteUrl(value: string | undefined): value is string {
  return Boolean(value && ABSOLUTE_URL_PATTERN.test(value));
}

function getBackendBaseUrl(): string {
  const publicApiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (isAbsoluteUrl(publicApiUrl)) {
    return publicApiUrl;
  }

  return process.env.BACKEND_URL || "http://localhost:8000";
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const apiKey = process.env.API_KEY;
  const payload = await request.text();

  try {
    const backendResponse = await fetch(
      `${getBackendBaseUrl()}/dashboard/location-report/export`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { [API_KEY_HEADER]: apiKey } : {}),
        },
        body: payload,
        cache: "no-store",
      }
    );

    const headers = new Headers();
    const contentType = backendResponse.headers.get("Content-Type");
    const contentDisposition = backendResponse.headers.get("Content-Disposition");

    if (contentType) {
      headers.set("Content-Type", contentType);
    }

    if (contentDisposition) {
      headers.set("Content-Disposition", contentDisposition);
    }

    return new NextResponse(backendResponse.body, {
      status: backendResponse.status,
      headers,
    });
  } catch (error) {
    console.error("Failed to proxy location report export", error);
    return NextResponse.json(
      { detail: "Failed to export location report" },
      { status: 502 }
    );
  }
}
