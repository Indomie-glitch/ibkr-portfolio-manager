import { describe, expect, it } from 'vitest'
import { isTextSize, stepTextSize, zoomFor } from './textSize.js'

describe('text size', () => {
  it('steps up and down and stops at the ends', () => {
    expect(stepTextSize('default', 1)).toBe('large')
    expect(stepTextSize('default', -1)).toBe('small')
    expect(stepTextSize('larger', 1)).toBe('larger')
    expect(stepTextSize('small', -1)).toBe('small')
  })

  it('treats an unknown size as the default', () => {
    expect(stepTextSize('huge', 1)).toBe('large')
    expect(zoomFor('huge')).toBe(1)
    expect(isTextSize('huge')).toBe(false)
    expect(isTextSize('large')).toBe(true)
  })
})
