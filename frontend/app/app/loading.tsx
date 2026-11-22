import LoadingState from "@/components/LoadingState";

export default function Loading() {
  return <LoadingState variant="dashboard" label="Loading your workspace" detail="Fetching your latest provider data…" />;
}
