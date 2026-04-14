import { useQuery } from "@tanstack/react-query"
import { getBoard } from "../api/board"
import { useUIStore } from "../stores/uiStore"

export function useBoard() {
  const activeFilters = useUIStore(s => s.activeFilters)
  return useQuery({
    queryKey: ["board", activeFilters],
    queryFn: () => getBoard(activeFilters),
    refetchInterval: 5000,
  })
}
