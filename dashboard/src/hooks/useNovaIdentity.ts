import { useQuery } from '@tanstack/react-query'
import { getNovaIdentity } from '../api'

export function useNovaIdentity() {
  const { data } = useQuery({
    queryKey: ['nova-identity'],
    queryFn: getNovaIdentity,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  return {
    name: data?.name ?? 'Nova',
    greeting: data?.greeting ?? '',
  }
}
