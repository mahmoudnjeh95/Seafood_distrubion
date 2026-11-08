import { getInstance, type Instance } from "@frutti/api";
import { useQuery } from "@tanstack/react-query";

// The last answer, kept on the device: the driver's phone is often offline and must still show the tag (D-283).
const STORAGE_KEY = "frutti.instance";

function remembered(): Instance | undefined {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? (JSON.parse(saved) as Instance) : undefined;
  } catch {
    return undefined;
  }
}

async function fetchInstance(): Promise<Instance> {
  const instance = await getInstance();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(instance));
  } catch {
    // Storage blocked: the tag still shows while online.
  }
  return instance;
}

/** Which copy of the application this is: production, or the training copy (D-283). */
export function useInstance(): Instance | undefined {
  return useQuery({
    queryKey: ["instance"],
    queryFn: fetchInstance,
    initialData: remembered,
    // Kept as initial data only: still asked once per page load.
    initialDataUpdatedAt: 0,
    staleTime: Infinity,
    retry: false,
  }).data;
}
