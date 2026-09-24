import { redirect } from "next/navigation";

/** Home redirects to Document Extraction. */
export default function Home() {
  redirect("/extract");
}
