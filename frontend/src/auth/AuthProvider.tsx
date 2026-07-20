import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, type ReactNode } from 'react'

import { api, ApiError } from '../api/client'
import type { User } from '../api/types'

interface AuthValue {
    user: User | null
    loading: boolean
    refresh: () => Promise<unknown>
    logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
    const queryClient = useQueryClient()
    useEffect(() => {
        void api.get('/auth/csrf')
    }, [])
    const query = useQuery({
        queryKey: ['me'],
        queryFn: () => api.get<User>('/auth/me'),
        retry: (count, error) => !(error instanceof ApiError && [401, 403].includes(error.status)) && count < 1
    })

    return (
        <AuthContext.Provider
            value={{
                user: query.data || null,
                loading: query.isLoading,
                refresh: query.refetch,
                logout: async () => {
                    await api.post('/auth/logout')
                    queryClient.setQueryData(['me'], null)
                }
            }}
        >
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth(): AuthValue {
    const value = useContext(AuthContext)
    if (!value) throw new Error('useAuth must be used inside AuthProvider')
    return value
}
