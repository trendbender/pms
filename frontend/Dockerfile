FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000

# dev server (compose mounts the source for hot reload)
CMD ["npm", "run", "dev"]
