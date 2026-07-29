import { authHandlers } from './auth'
import { kbHandlers } from './knowledge-base'
import { documentHandlers } from './document'
import { faqHandlers } from './faq'
import { searchHandlers } from './search'

export const handlers = [
  ...authHandlers,
  ...kbHandlers,
  ...documentHandlers,
  ...faqHandlers,
  ...searchHandlers,
]
