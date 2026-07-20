import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
    cleanup()
    document.cookie = 'csrftoken=; Max-Age=0; Path=/'
    window.location.hash = ''
})
