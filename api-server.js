const express = require("express");
const cors = require("cors");
const app = express();
const data = require("./data");

// Применяем промежуточное ПО express
app.use(cors({ origin: "*" }));
app.use(express.json());

// Добавляем новый обработчик для запросов с Telegram-бота
app.get("/search/:entry", (req, res) => {
  const entry = req.params.entry;
  const language = "en"; // Используем английский язык по умолчанию
  
  console.log(`Поиск слова: ${entry} (язык: ${language})`);
  
  // Делаем прямой запрос к существующему API через модуль request
  const request = require("request");
  const url = `http://localhost:8000/api/dictionary/${language}/${entry}`;
  
  request(url, (error, response, html) => {
    if (!error && response.statusCode == 200) {
      try {
        const data = JSON.parse(html);
        res.status(200).json(data);
      } catch (e) {
        res.status(500).json({
          error: "Ошибка при обработке ответа от API",
          details: e.message
        });
      }
    } else {
      res.status(404).json({
        error: "Слово не найдено или произошла ошибка при обработке запроса",
        word: entry
      });
    }
  });
});

// Используем существующие роуты из data.js
app.use("/", data);

// Запускаем сервер
const PORT = process.env.PORT || 8000;
app.listen(PORT, () => {
  console.log(`API сервер запущен на порту ${PORT}`);
  console.log("Доступные эндпоинты:");
  console.log("- /search/:word - поиск слова (для бота)");
  console.log("- /api/dictionary/:language/:word - прямой доступ к словарю");
});
