// react-query wrappers over src/lib/api.js. Thin, declarative, with sensible
// polling for the live-ops feel. All underlying calls degrade to sentinels,
// so these never throw — `data` is always defined after first load.
import { useQuery } from '@tanstack/react-query'
import {
  getHealth, getSites, getEvents, getEventTrack, getAnomalies,
  getSources, getAlerts, getInvestigations,
} from '@/lib/api'

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 10_000 })

export const useSites = () =>
  useQuery({ queryKey: ['sites'], queryFn: getSites })

export const useEvents = () =>
  useQuery({ queryKey: ['events'], queryFn: getEvents, refetchInterval: 15_000 })

export const useEventTrack = (id) =>
  useQuery({
    queryKey: ['track', id],
    queryFn: () => getEventTrack(id),
    enabled: !!id,
  })

export const useAnomalies = () =>
  useQuery({ queryKey: ['anomalies'], queryFn: getAnomalies, refetchInterval: 30_000 })

export const useSources = () =>
  useQuery({ queryKey: ['sources'], queryFn: getSources, refetchInterval: 20_000 })

export const useAlerts = () =>
  useQuery({ queryKey: ['alerts'], queryFn: getAlerts, refetchInterval: 20_000 })

export const useInvestigations = () =>
  useQuery({ queryKey: ['investigations'], queryFn: getInvestigations })
