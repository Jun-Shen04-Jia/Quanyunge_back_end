from flask import Flask, jsonify, request
from flask_restful import Api, Resource, reqparse
from flask_restx import Api, Resource, reqparse
import requests
import sqlite3
import os
import time
import base64
from PIL import Image, ImageDraw
import numpy as np
import torch
from torchvision import models, transforms
from Se_Resnet import SE_ResNet50
from PIL import Image, ImageDraw
import numpy as np
import os
import numpy as np
from PIL import Image, ImageOps, ImageDraw, ImageFont
import math
import datetime
import colorsys
import csv
import cv2
import shutil
import io

app = Flask(__name__)
api = Api(app, doc_root='/api-docs', ui_root='/swagger-ui')

# 配置数据库
app.config['DATABASE'] = 'Coin_Select.db'
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 例如，设置为 16 MB


# 微信小程序的 AppID 和 AppSecret
APP_ID = 'wx9c584575c038687e'
APP_SECRET = '7b35ffb81d968d656783077627ee8faf'


# 从微信小程序获取 openid
@app.route('/get_openid', methods=['POST'])
def get_openid():
    # 从请求中获取 code
    data = request.get_json()
    code = data.get('code')

    if not code:
        return jsonify({'error': '缺少 code 参数'}), 400

    # 调用微信的 jscode2session 接口
    url = f"https://api.weixin.qq.com/sns/jscode2session?appid={APP_ID}&secret={APP_SECRET}&js_code={code}&grant_type=authorization_code"

    try:
        # 请求微信服务器换取 openid 和 session_key
        response = requests.get(url)
        wx_data = response.json()

        if 'errcode' in wx_data:
            return jsonify({'error': wx_data.get('errmsg')}), 400

        openid = wx_data.get('openid')
        session_key = wx_data.get('session_key')

        # 返回 openid 给小程序端
        return jsonify({'openid': openid})

    except Exception as e:
        print(f"获取 openid 失败: {e}")
        return jsonify({'error': '服务器错误'}), 500


def get_db():
    """Connects to the specific database."""
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row  # Enables dictionary-like access to rows
    return db


# 用户
@api.doc(description='Get user information')
class UserResource(Resource):
    def get(self, id):
        db = get_db()
        user = db.execute('SELECT * FROM User WHERE ID = ?', (id,)).fetchone()
        db.close()
        # 将coin字典转换为可变的字典
        user = dict(user)
        # 获取Coins文件夹的路径
        user_folder_path = os.path.join(os.getcwd(), 'Profile')
        # 读取Coins文件夹下的图片
        user_photo_path = os.path.join(user_folder_path, str(user['profile_photo']))
        with open(user_photo_path, 'rb') as f:
            user_photo = f.read()

        # 将图片转换为Base64编码的字符串
        user_photo_base64 = base64.b64encode(user_photo).decode('utf-8')

        # 将Base64编码的字符串保存回字典
        user['coin_photo'] = user_photo_base64
        return jsonify(user if user else None)

    def post(self, id):
        db = get_db()
        # 创建不含 profile_photo 字段的 User 表
        db.execute('''
        CREATE TABLE IF NOT EXISTS User (
            ID TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        ''')
        db.commit()

        # 检查数据库中是否已存在该 ID
        existing_user = db.execute('SELECT * FROM User WHERE ID = ?', (id,)).fetchone()

        if existing_user:
            # 如果用户已存在，返回 409 错误（冲突）或其他适当的响应
            db.close()
            return jsonify({"message": "User with this ID already exists."})

        # 解析请求数据，仅获取 name 参数
        parser = reqparse.RequestParser()
        parser.add_argument('name', type=str, required=True)
        args = parser.parse_args()
        name = args['name']

        # 插入新用户数据，不含 profile_photo 字段
        db.execute('INSERT INTO User (ID, name) VALUES (?, ?)', (id, name))
        db.commit()
        db.close()

        return jsonify('注册成功')

    def patch(self, id):
        db = get_db()
        parser = reqparse.RequestParser()
        parser.add_argument('name', type=str, required=True)
        # profile_photo为base64编码的字符串
        parser.add_argument('profile_photo', type=str, required=True)
        args = parser.parse_args()
        name = args['name']
        profile_photo = args['profile_photo']
        # profile_photo为base64编码的字符串，需要解码
        profile_photo = base64.b64decode(profile_photo)
        # 保存图片
        profile_photo_path = os.path.join(os.getcwd(), 'Profile', str(id))
        with open(profile_photo_path, 'wb') as f:
            f.write(profile_photo)
        db.execute('UPDATE User SET name=?, profile_photo=? WHERE ID=?', (name, str(id) + '.jpg', id))
        db.commit()
        db.close()
        return '', 204


# 钱币类别
@api.doc(description='Get a list of coin classes')
class ClassesResource(Resource):
    def get(self):
        print('get classes')
        db = get_db()
        classes = db.execute('SELECT class_id, class_name, class_story FROM Class').fetchall()
        db.close()

        # 提取 class_name 列的值并放入一个列表
        class_id = [c['class_id'] for c in classes]
        class_names = [c['class_name'] for c in classes]
        class_story = [c['class_story'] for c in classes]

        # 将 class_names 列表包装在字典中返回
        return jsonify({
            "class": [dict(c) for c in classes],
            "class_story": class_story
        })


# 钱币类别下钱币列表
@api.doc(description='Get a list of coins for a specific class')
class CoinsResource(Resource):
    def get(self, class_id):
        db = get_db()
        coins = db.execute('SELECT coin_id, coin_name FROM Coin WHERE class_id = ?', (class_id,)).fetchall()
        db.close()

        db = get_db()
        class_story = db.execute('SELECT class_story FROM Class WHERE class_id = ?', (class_id,)).fetchone()
        db.close()

        # 将钱币列表和类别故事一起返回
        response = {
            'coins': [dict(coin) for coin in coins],
            'class_story': dict(class_story) if class_story else None
        }
        return jsonify(response)


# 钱币详情
@api.doc(description='Get detailed information about a coin')
class CoinResource(Resource):
    def get(self, coin_id):
        db = get_db()
        coin = db.execute('SELECT * FROM Coin WHERE coin_id = ?', (coin_id,)).fetchone()
        db.close()

        if coin is None:
            return jsonify({'error': 'Coin not found'}), 404

        # 将coin字典转换为可变的字典
        coin = dict(coin)
        # 获取Coins文件夹的路径
        coins_folder_path = os.path.join(os.getcwd(), 'Coins')
        # 读取Coins文件夹下的图片
        coin_photo_path = os.path.join(coins_folder_path, str(coin['coin_photo']))
        with open(coin_photo_path, 'rb') as f:
            coin_photo = f.read()

        # 将图片转换为Base64编码的字符串
        coin_photo_base64 = base64.b64encode(coin_photo).decode('utf-8')

        # 将Base64编码的字符串保存回字典
        coin['coin_photo'] = coin_photo_base64

        # 从数据库Transactions获取该硬币交易记录
        db = get_db()
        transactions = db.execute('SELECT * FROM Transactions WHERE coin_id = ?', (coin_id,)).fetchall()
        db.close()
        # 将交易记录转换为可变的字典
        transactions = [dict(t) for t in transactions]
        # 获取交易记录中的图片
        trans_folder_path = os.path.join(os.getcwd(), 'Transaction')
        for t in transactions:
            transaction_photo_path = os.path.join(trans_folder_path, str(t['trans_photo']))
            with open(transaction_photo_path, 'rb') as f:
                transaction_photo = f.read()
            # 将图片转换为Base64编码的字符串
            transaction_photo_base64 = base64.b64encode(transaction_photo).decode('utf-8')
            # 将Base64编码的字符串保存回字典
            t['transaction_photo'] = transaction_photo_base64
        # 将交易记录保存回字典coin
        coin['transactions'] = transactions
        return jsonify(coin)


# 浏览足迹
@api.doc(description='Get a list of coins that the user has viewed')
class HistoryResource(Resource):
    def get(self, id):
        db = get_db()
        history = db.execute('SELECT * FROM Footprint Where ID=?', (id,)).fetchall()
        db.close()
        # 从coin中获取每个coin_id名称与图片
        for h in history:
            db = get_db()
            coin = db.execute('SELECT coin_id, coin_name, coin_photo FROM Coin WHERE coin_id=?',
                              (h['coin_id'],)).fetchone()
            db.close()
            h['coin_name'] = coin['coin_name']
            # 获取Coins文件夹的路径
            coins_folder_path = os.path.join(os.getcwd(), 'Coins')
            # 读取Coins文件夹下的图片
            coin_photo_path = os.path.join(coins_folder_path, str(coin['coin_photo']))
            with open(coin_photo_path, 'rb') as f:
                coin_photo = f.read()

            # 将图片转换为Base64编码的字符串
            coin_photo_base64 = base64.b64encode(coin_photo).decode('utf-8')

            # 将Base64编码的字符串保存回字典
            h['coin_photo'] = coin_photo_base64
        # 显示时从后往前显示
        return jsonify([dict(h) for h in history])

    # 添加浏览记录
    def post(self, id):
        db = get_db()
        parser = reqparse.RequestParser()
        parser.add_argument('coin_id', type=int, required=True)
        args = parser.parse_args()
        coin_id = args['coin_id']
        # 确保数据库里没有相同信息，如果有先删除
        db.execute('DELETE FROM Footprint WHERE ID=? AND coin_id=?', (id, coin_id))
        db.execute('INSERT INTO Footprint (ID, coin_id) VALUES (?, ?)', (id, coin_id))
        db.commit()
        db.close()
        return '', 201


# 用户收藏
@api.doc(description='Get a list of coins that the user has favorited')
class FavoriteResource(Resource):
    def get(self, id):
        db = get_db()

        # 获取用户收藏的 coin_id 列表
        collection = db.execute('SELECT * FROM Favorite WHERE ID=?', (id,)).fetchall()

        # 将收藏的每个 coin 转换为可修改的字典
        favorites = []
        for c in collection:
            c = dict(c)  # 将 sqlite3.Row 转换为字典

            # 获取 coin 的详细信息
            coin = db.execute('SELECT coin_id, coin_name, coin_photo FROM Coin WHERE coin_id=?',
                              (c['coin_id'],)).fetchone()

            if coin:
                # 将 coin 的信息添加到收藏字典中
                c['coin_name'] = coin['coin_name']

                # 获取 Coins 文件夹的路径并读取图片
                coins_folder_path = os.path.join(os.getcwd(), 'Coins')
                coin_photo_path = os.path.join(coins_folder_path, str(coin['coin_photo']))

                try:
                    with open(coin_photo_path, 'rb') as f:
                        coin_photo = f.read()
                    # 将图片转换为 Base64 编码的字符串
                    c['coin_photo'] = base64.b64encode(coin_photo).decode('utf-8')
                except FileNotFoundError:
                    c['coin_photo'] = None  # 若图片不存在，则设置为 None

            favorites.append(c)

        db.close()

        # 返回时将收藏列表反转，使其从后往前显示
        return jsonify(favorites[::-1])


# 查询单硬币是否收藏
@api.doc(description='Get whether a coin that the user has favorited')
class FavoriteCoinResource(Resource):
    def get(self, id, coin_id):
        db = get_db()
        collection = db.execute('SELECT * FROM Favorite WHERE ID=? AND coin_id=?', (id, coin_id)).fetchone()
        db.close()
        return jsonify(1 if collection else 2)

    def post(self, id, coin_id):
        db = get_db()
        db.execute('INSERT INTO Favorite (ID, coin_id) VALUES (?, ?)', (id, coin_id))
        db.commit()
        db.close()
        return jsonify({"save": 1})

    def delete(self, id, coin_id):
        db = get_db()
        db.execute('DELETE FROM Favorite WHERE ID=? AND coin_id=?', (id, coin_id))
        db.commit()
        db.close()
        return jsonify({"save": 1})


@api.doc(description='Delete all recognition records for a specific user')
class ClearRecognitionResource(Resource):
    def post(self, id):
        db = get_db()
        fileName = db.execute('SELECT rec_photo FROM Recognition WHERE ID=?', (id,))
        for file in fileName:
            recognition_folder_path = os.path.join(os.getcwd(), 'Recognition')
            rec_photo_path = os.path.join(recognition_folder_path, str(file['rec_photo']))
            print("clear path: ", rec_photo_path)
            try:
                os.remove(rec_photo_path)
            except FileNotFoundError:
                return jsonify({"clear": 0})
        db.execute('DELETE FROM Recognition WHERE ID=?', (id,))
        db.commit()
        db.close()
        return jsonify({"clear": 1})


@api.doc(description='Get a list of recognition records')
class RecognitionResource(Resource):
    def get(self, id, coin_id):
        db = get_db()
        print(id, coin_id)
        recognition = db.execute('SELECT * FROM Recognition WHERE ID=?', (id,)).fetchall()
        db.close()

        if recognition is None:
            return jsonify(None)

        # 将 recognition 转换为字典列表
        recognition = [dict(row) for row in recognition]
        print(recognition)

        for r in recognition:
            db = get_db()
            coin = db.execute('SELECT coin_id, coin_name FROM Coin WHERE coin_id=?', (r['coin_id'],)).fetchone()
            db.close()

            if coin:
                # 将 coin 也转换为字典，以便可以访问其数据
                coin = dict(coin)
                r['coin_name'] = coin['coin_name']  # 现在可以安全修改

            # 获取Recognition文件夹的路径
            recognition_folder_path = os.path.join(os.getcwd(), 'Recognition')
            # 读取Recognition文件夹下的图片
            rec_photo_path = os.path.join(recognition_folder_path, str(r['rec_photo']))
            print(rec_photo_path)
            try:
                with open(rec_photo_path, 'rb') as f:
                    rec_photo = f.read()
                rec_photo_base64 = base64.b64encode(rec_photo).decode('utf-8')
                r['rec_photo'] = rec_photo_base64
            except IOError:
                r['rec_photo'] = None  # 如果文件不存在或无法读取，则设置为None

        return jsonify(recognition)

    def post(self, id, coin_id):
        try:
            # 设置当前时间戳为图片文件名
            photo_name = f"{int(time.time())}{id}{coin_id}.jpg"
            # rec_id = db.execute('SELECT COUNT(*) FROM Recognition').fetchone()[0] + 1
            # print("rec_id: ",rec_id)
            # 设置图片的原始路径和目标路径
            cropped_image_path = os.path.join(os.getcwd(), 'Recognition', 'cropped_image.jpg')
            rec_photo_path = os.path.join(os.getcwd(), 'Recognition', photo_name)

            # 尝试移动文件
            shutil.move(cropped_image_path, rec_photo_path)

            # 获取数据库连接
            db = get_db()
            try:
                # 尝试插入数据库记录
                db.execute('INSERT INTO Recognition (ID, coin_id, rec_photo) VALUES (?, ?, ?)',
                           (id, coin_id, photo_name))
                db.commit()
            except sqlite3.IntegrityError as e:
                db.rollback()  # 回滚在发生异常时的更改
                return jsonify({"error": "A record with the same ID and coin_id already exists."})
            except Exception as e:
                db.rollback()  # 回滚在发生其他异常时的更改
                return jsonify({"error": "Database error"})
            finally:
                db.close()  # 确保数据库连接被关闭

            # 如果一切顺利
            return jsonify({"save": 1})
        except FileNotFoundError:
            # 如果源文件不存在
            return jsonify({"error": "Source file not found"}), 404
        except Exception as e:
            # 处理其他未预见的错误
            return jsonify({"error": "An error occurred", "details": str(e)}), 500


@api.doc(description='Get the coordinates of the four corners of the coin')
class CoinRecognition(Resource):
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('image', type=str, required=True)
        args = parser.parse_args()
        image_data = args['image']
        # image_data为base64编码的字符串，需要解码
        image_path = os.path.join(os.getcwd(), 'Recognition', 'rec_image.jpg')
        image_data = base64.b64decode(image_data)
        with open(image_path, 'wb') as f:
            f.write(image_data)
        # 读取图片
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        edges = cv2.Canny(img, 100, 200)
        dilationKernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3), (1, 1))
        cv2.dilate(edges, dilationKernel, edges)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        matchingContours = []
        maxr = -1
        maxellipse = ()
        width, height = img.shape
        for currentContour in range(0, len(contours)):
            if len(contours[currentContour]) < 5 or cv2.contourArea(contours[currentContour]) <= 100:
                continue
            # 2.2 创建形状包围轮廓，得到轮廓的边界矩形的顶点和其相反点
            boundingRectVals = cv2.boundingRect(contours[currentContour])  # x y w h
            boundingRect_x, boundingRect_y, boundingRect_w, boundingRect_h = cv2.boundingRect(contours[currentContour])
            p1 = (boundingRect_x, boundingRect_y)
            p2 = (boundingRect_x + boundingRect_w, boundingRect_y + boundingRect_h)
            bottom = (boundingRect_x, boundingRect_y + boundingRect_h + 50)
            # 2.3 求轮廓的外接椭圆
            ellipse = cv2.fitEllipse(contours[currentContour])  # [ (x, y) , (a, b), angle ] 椭圆中心位置，长短轴，旋转角度
            x = ellipse[0][0]
            y = ellipse[0][1]
            a = ellipse[1][0]
            b = ellipse[1][1]
            if 0.8 > a / b or a / b > 1.25:
                continue
            r = (a + b) / 2
            if (r > maxr and maxr < min(width, height) * 1.05):
                maxr = r
                maxellipse = ellipse
        if maxr == -1:
            maxr = (width + height) / 8 * 3
            x = width / 2
            y = height / 2
        else:
            x = maxellipse[0][0]
            y = maxellipse[0][1]
        # 得出四角坐标
        x1 = int(x - maxr / 2)
        y1 = int(y - maxr / 2)
        x2 = int(x + maxr / 2)
        y2 = int(y + maxr / 2)
        # 返回四角坐标 4个（x,y)
        return jsonify({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})

    # 识别硬币
    def get(self):
        # 获取四角坐标，对于rec_image.jpg裁剪
        parser = reqparse.RequestParser()
        parser.add_argument('x1', type=float, required=True)
        parser.add_argument('y1', type=float, required=True)
        parser.add_argument('x2', type=float, required=True)
        parser.add_argument('y2', type=float, required=True)
        args = parser.parse_args()
        x1 = args['x1']
        y1 = args['y1']
        x2 = args['x2']
        y2 = args['y2']
        # 读取图片
        image_path = os.path.join(os.getcwd(), 'Recognition', 'rec_image.jpg')
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        # 裁剪图片
        cropped_img = img[int(y1):int(y2), int(x1):int(x2)]
        # 保存裁剪后的图片
        cropped_img_path = os.path.join(os.getcwd(), 'Recognition', 'cropped_image.jpg')
        imgsource = os.path.join(os.getcwd(), 'Recognition', 'rec_image.jpg')
        try:
            cv2.imwrite(cropped_img_path, cropped_img)
            imgsource = cropped_img_path
        except Exception as e:
            print(e)

        # 定义图像预处理转换
        preprocess = transforms.Compose([
            transforms.Resize((28, 28)),
            transforms.Grayscale(num_output_channels=1),  # 将图像转换为灰度图像
            transforms.ToTensor()  # 转换为Tensor
        ])
        model_save_path_SE50 = 'best_model_SE.pth'
        # 加载图像并进行预处理
        imgsource = os.path.join(os.getcwd(), 'Recognition', 'rec_image.jpg')
        minAreaOfCircle = 100
        # 应用Canny边缘检测算法
        cannyThreshold = 100  # canny 算子的低阈值
        cannyThreshold2 = 200
        highThreshold = 1000
        lowThreshold = 10
        maxr = -1
        cropped_img = np.zeros((0, 0), dtype=np.uint8)
        cropped_img1 = np.zeros((0, 0), dtype=np.uint8)
        dot = 0
        maxellipse = ()
        f = True
        imgs = cv2.imread(imgsource, cv2.IMREAD_COLOR)
        img = cv2.imread(imgsource, cv2.IMREAD_GRAYSCALE)
        while f:
            edges = cv2.Canny(img, cannyThreshold, cannyThreshold2)
            original_edges = edges
            '''dilationKernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3), (1, 1))
            cv2.dilate(edges, dilationKernel, edges)'''
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            matchingContours = []
            circle = False
            for currentContour in range(0, len(contours)):
                if len(contours[currentContour]) < 5 or cv2.contourArea(contours[currentContour]) <= minAreaOfCircle:
                    continue
                # 2.2 创建形状包围轮廓，得到轮廓的边界矩形的顶点和其相反点
                boundingRectVals = cv2.boundingRect(contours[currentContour])  # x y w h
                boundingRect_x, boundingRect_y, boundingRect_w, boundingRect_h = cv2.boundingRect(
                    contours[currentContour])
                p1 = (boundingRect_x, boundingRect_y)
                p2 = (boundingRect_x + boundingRect_w, boundingRect_y + boundingRect_h)
                bottom = (boundingRect_x, boundingRect_y + boundingRect_h + 50)
                # 2.3 求轮廓的外接椭圆
                ellipse = cv2.fitEllipse(contours[currentContour])  # [ (x, y) , (a, b), angle ] 椭圆中心位置，长短轴，旋转角度
                x = ellipse[0][0]
                y = ellipse[0][1]
                a = ellipse[1][0]
                b = ellipse[1][1]
                if 0.8 > a / b or a / b > 1.25:
                    continue
                r = (a + b) / 2
                if (r > maxr):
                    maxr = r
                    maxellipse = ellipse
                if (r / maxr > 0.8 and r / maxr < 1.25):
                    circle = True

            if maxellipse:  # Check if maxellipse is not an empty tuple
                maxellipse = (maxellipse[0], (maxr, maxr), maxellipse[2])
                cv2.ellipse(imgs, maxellipse, (0, 0, 255), 3, cv2.LINE_AA)
                x = maxellipse[0][0]
                y = maxellipse[0][1]
                # 确定图像的尺寸
                height, width = original_edges.shape
                # 初始化计数器
                total_pixels = 0
                pixels_greater_than_zero = 0
                # 遍历图像中的所有像素
                for i in range(height):
                    for j in range(width):
                        # 检查像素是否在圆内
                        if (i - y) ** 2 + (j - x) ** 2 <= (maxr / 2) ** 2:
                            total_pixels += 1
                            # 检查像素值是否大于0
                            if original_edges[i, j] > 0:
                                pixels_greater_than_zero += 1
                        else:
                            original_edges[i, j] = 0
                half_size = maxr // 2
                top_left = (int(x - half_size), int(y - half_size))
                bottom_right = (int(x + half_size), int(y + half_size))
                # 裁剪图像
                img_color = original_edges  # 读取彩色图像用于裁剪
                cropped_img = img_color[max(top_left[1], 0):min(bottom_right[1], height),
                              max(top_left[0], 0):min(bottom_right[0], width)]
                dot = pixels_greater_than_zero / total_pixels
                cropped_img1 = cropped_img
                if pixels_greater_than_zero / total_pixels > 0.1 and pixels_greater_than_zero / total_pixels < 0.13:
                    f = False
                    print(os.path.basename(imgsource), total_pixels, pixels_greater_than_zero,
                          pixels_greater_than_zero / total_pixels, cannyThreshold, cannyThreshold2)
                    print(os.path.basename(imgsource), maxr, x, y, width, height)
                else:
                    if pixels_greater_than_zero / total_pixels > 0.13:
                        lowThreshold = cannyThreshold2
                        cannyThreshold2 = (lowThreshold + highThreshold) // 2
                        cannyThreshold = cannyThreshold2 // 2
                        if abs(lowThreshold - highThreshold) < 5:
                            print(os.path.basename(imgsource), total_pixels, pixels_greater_than_zero,
                                  pixels_greater_than_zero / total_pixels, cannyThreshold, cannyThreshold2)
                            print(os.path.basename(imgsource), maxr, x, y, width, height)
                            f = False
                            if highThreshold > 990:
                                f = True
                                highThreshold *= 2
                                cannyThreshold2 = (lowThreshold + highThreshold) // 2
                                cannyThreshold = cannyThreshold2 // 2
                    else:
                        highThreshold = cannyThreshold2
                        cannyThreshold2 = (lowThreshold + highThreshold) // 2
                        cannyThreshold = cannyThreshold2 // 2
                        if abs(lowThreshold - highThreshold) < 5:
                            print(os.path.basename(imgsource), total_pixels, pixels_greater_than_zero,
                                  pixels_greater_than_zero / total_pixels, cannyThreshold, cannyThreshold2)
                            print(os.path.basename(imgsource), maxr, x, y, width, height)
                            f = False
                            if highThreshold * 2 > 990:
                                f = True
                                highThreshold *= 2
                                cannyThreshold2 = (lowThreshold + highThreshold) // 2
                                cannyThreshold = cannyThreshold2 // 2
            else:
                f = False
                print(os.path.basename(imgsource))
        if cropped_img1 is not None and cropped_img1.any():
            cropped_img = cropped_img1

        if maxellipse:
            image_path = os.path.join(os.getcwd(), 'Recognition', 'rec_image.jpg')
            cv2.imwrite(image_path, cropped_img)
        image_path = os.path.join(os.getcwd(), 'Recognition', 'rec_image.jpg')
        img = Image.open(image_path)
        img_t = preprocess(img)
        # 添加批次维度
        batch_t = torch.unsqueeze(img_t, 0)

        # 加载模型
        model = SE_ResNet50()
        # 修改最后一层以适应你的分类任务（假设你有5个类别）
        num_ftrs = model.linear.in_features  # 使用正确的层名 'linear'
        model.linear = torch.nn.Linear(num_ftrs, 5)  # 假设你有5个类别
        # 加载预训练的模型权重
        model.load_state_dict(torch.load(model_save_path_SE50, map_location=torch.device('cpu')))
        model.eval()

        # 进行预测
        with torch.no_grad():
            output = model(batch_t)
        # 获取预测标签
        _, preds = torch.max(output, 1)
        print("预测标签：", preds.item() + 1)
        # 输出预测标签
        coin_id = preds.item() + 1
        # 将识别信息存入数据库
        return jsonify({'coin_id': coin_id})


# 生成硬币
@api.doc(description='Generate a coin')
class CoinGeneration(Resource):
    def post(self, id):
        # 获取text1,text2
        parser = reqparse.RequestParser()
        parser.add_argument('text1', type=str, required=True)
        parser.add_argument('text2', type=str, required=True)
        args = parser.parse_args()
        text1 = args['text1']
        text2 = args['text2']
        print(text1, text2)
        # 获取图片base64编码并解码保存
        parser = reqparse.RequestParser()
        parser.add_argument('image', type=str, required=True)
        args = parser.parse_args()
        image_data = args['image']
        coin_photo_path = os.path.join(os.getcwd(), 'photo.jpg')
        image_data = base64.b64decode(image_data)
        with open(coin_photo_path, 'wb') as f:
            f.write(image_data)
        a = np.asarray(Image.open("photo.jpg").convert("L")).astype("float")
        depth = 30  # 设置深度为10
        grad = np.gradient(a)  # 对数组a求梯度
        grad_x, grad_y = grad
        grad_x = grad_x * depth / 100
        grad_y = grad_y * depth / 100
        A = np.sqrt(grad_x ** 2 + grad_y ** 2 + 1.)
        uni_x = grad_x / A
        uni_y = grad_y / A
        uni_z = 1. / A
        vec_el = np.pi / 2.2  # θ角度
        vec_az = np.pi / 4.  # α角度
        dx = np.cos(vec_el) * np.cos(vec_az)
        dy = np.cos(vec_el) * np.sin(vec_az)
        dz = np.sin(vec_el)
        b = 255 * (dx * uni_x + dy * uni_y + dz * uni_z)
        b = b.clip(0, 255)
        im = Image.fromarray(b.astype('uint8'))
        # 将图片按照当前黑白色改为金色
        im = im.convert('RGB')
        data = im.getdata()
        im.save("sketch.jpg")
        background_gold = (219, 177, 152)  # 浅金色
        line_gold = (92, 56, 30)
        background_gold1 = np.array((219, 177, 152))
        line_gold1 = np.array((92, 56, 30))
        image = Image.open('sketch.jpg')
        images = np.array(image)
        images = (images * (background_gold1 - line_gold1) / 255 + line_gold1).astype(np.uint8)

        # 保存图像
        result_image = Image.fromarray(images)
        image = result_image
        width, height = image.size

        if width > height:
            height = int(700 * height / width)
            width = 700

        else:
            width = int(700 * width / height)
            height = 700

        image = image.resize((width, height), Image.LANCZOS)

        # 创造一个新的图片中间是半径800的圆，颜色background_gold，边框颜色line_gold,背景为白色
        new_image = Image.new("RGB", (1600, 1600), "white")
        draw = ImageDraw.Draw(new_image)
        draw.ellipse((0, 0, 1600, 1600), fill=background_gold, outline=line_gold)

        # image放在new_image正中间（两个图片中心一样），然后保存
        # Calculate the position to paste the image in the center of the new image
        paste_position = ((new_image.width - image.width) // 2, (new_image.height - image.height) // 2)

        # Paste the resized image onto the new image, centered
        new_image.paste(image, paste_position)
        text_size2 = 100
        text_size = 100
        font = ImageFont.truetype("./font/simkai.ttf", size=text_size)
        font2 = ImageFont.truetype("./font/simkai.ttf", size=text_size2)
        draw = ImageDraw.Draw(new_image)
        little_r = 650
        little_r2 = little_r - text_size2
        # 求arcsin，答案角度在0-180之间
        angle = (np.arcsin(text_size / 2 / ((-np.cos(np.arcsin(
            text_size / little_r / 2)) * 2 * little_r * text_size + little_r * little_r + text_size * text_size) ** 0.5)) * 180 / np.pi) * 2
        angle2 = (np.arcsin(text_size2 / 2 / ((-np.cos(np.arcsin(
            text_size2 / little_r2 / 2)) * 2 * little_r2 * text_size2 + little_r2 * little_r2 + text_size2 * text_size2) ** 0.5)) * 180 / np.pi) * 2
        len_text = len(text1) // 2
        len_text2 = len(text2) // 2
        fill = '#D9AF96'  # 文字无填充色，即空心
        stroke_width = 4  # 设置描边的宽度
        stroke_fill = '#6A462C'  # 设置描边的颜色
        if len(text1) % 2 == 0:
            angles = angle * (len_text - 0.5)
        else:
            angles = angle * (len_text)
        if len(text2) % 2 == 0:
            angles2 = angle2 * (len_text2 - 0.5)
        else:
            angles2 = angle2 * (len_text2)
        # Draw each character
        for char in text1:
            # Draw the character on the image,背景透明
            char_image = Image.new('RGB', (text_size, text_size), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_image)
            # 在图像上绘制字符
            char_draw.text((0, 0), char, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, font=font)
            rotated_char_image = char_image.rotate(angles, expand=True)
            # rotated_char_image.save(char + '.png')  #
            # 将图片的黑色变为透明
            rotated_char_image = rotated_char_image.convert('RGBA')
            data = rotated_char_image.getdata()
            new_data = []
            for item in data:
                if item[0] == 0 and item[1] == 0 and item[2] == 0:
                    new_data.append(background_gold)
                else:
                    new_data.append(item)
            rotated_char_image.putdata(new_data)
            # Move to the right for the next character
            if angles > 0:
                rotated_char_position = (
                    int(800 - little_r * math.sin((angles + 0.5 * angle) * np.pi / 180) - text_size * math.sin(
                        angles * np.pi / 180)), int(800 - little_r * math.cos((angles + 0.5 * angle) * np.pi / 180)))
            else:
                rotated_char_position = (int(800 - little_r * math.sin((angles + 0.5 * angle) * np.pi / 180)),
                                         int(-text_size * math.sin(angles * np.pi / 180) + 800 - little_r * math.cos(
                                             (angles + 0.5 * angle) * np.pi / 180)))
            # Paste the rotated character onto the main image
            new_image.paste(rotated_char_image, rotated_char_position)
            angles -= angle
            # 移动到下一个字符的右侧
        for char in text2:
            # Draw the character on the image,背景透明
            char_image = Image.new('RGB', (text_size2, text_size2), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_image)
            # 在图像上绘制字符
            char_draw.text((0, 0), char, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill, font=font2)
            angles1 = 0 - angles2
            rotated_char_image = char_image.rotate(angles1, expand=True)
            # rotated_char_image.save(char + '.png')  #
            # 将图片的黑色变为透明
            rotated_char_image = rotated_char_image.convert('RGBA')
            data = rotated_char_image.getdata()
            new_data = []
            for item in data:
                if item[0] == 0 and item[1] == 0 and item[2] == 0:
                    new_data.append(background_gold)
                else:
                    new_data.append(item)
            rotated_char_image.putdata(new_data)
            # Move to the right for the next character
            if angles2 > 0:
                rotated_char_position = (int(800 - little_r2 * math.sin((angles2 + 0.5 * angle2) * np.pi / 180)),
                                         int(text_size2 * math.sin(angles2 * np.pi / 180) + 800 + little_r2 * math.cos(
                                             (angles2 + 0.5 * angle2) * np.pi / 180)))
            else:
                rotated_char_position = (
                    int(800 - little_r2 * math.sin((angles2 + 0.5 * angle2) * np.pi / 180) + text_size2 * math.sin(
                        angles2 * np.pi / 180)),
                    int(800 + little_r2 * math.cos((angles2 + 0.5 * angle2) * np.pi / 180)))
            # Paste the rotated character onto the main image
            new_image.paste(rotated_char_image, rotated_char_position)
            angles2 -= angle2
        # 绕画布上800,800画一个半径620的圆
        # 获取时间戳按秒精确度转为整数

        # 创建一个datetime对象
        now = datetime.datetime.now()

        # 转换为Unix时间戳
        timestamp = now.timestamp()

        timelist = []
        for i in range(8):
            for j in range(3):
                for k in range(4):
                    timelist.append([i, j, k])
        # 把timelist打乱
        np.random.shuffle(timelist)

        indexs = int(timestamp) % len(timelist)
        inner = timelist[indexs][0]
        match inner:
            case 0:
                timestamp = now.timestamp()
            case 1:
                draw.ellipse(((300, 300), (1300, 1300)), fill=None, outline=line_gold, width=5)
            case 2:
                draw.ellipse(((310, 310), (1290, 1290)), fill=None, outline=line_gold, width=5)
                draw.ellipse(((300, 300), (1300, 1300)), fill=None, outline=line_gold, width=5)
            case 3:
                for i in range(0, 360, 2):
                    x = 800 + 500 * math.sin(i * np.pi / 180)
                    y = 800 + 500 * math.cos(i * np.pi / 180)
                    x1 = x - 5
                    y1 = y - 5
                    x2 = x + 5
                    y2 = y + 5
                    draw.ellipse(((x1, y1), (x2, y2)), fill=line_gold, width=1)
            case 4:
                draw.ellipse(((310, 310), (1290, 1290)), fill=None, outline=line_gold, width=5)
                for i in range(0, 360, 2):
                    x = 800 + 500 * math.sin(i * np.pi / 180)
                    y = 800 + 500 * math.cos(i * np.pi / 180)
                    x1 = x - 5
                    y1 = y - 5
                    x2 = x + 5
                    y2 = y + 5
                    draw.ellipse(((x1, y1), (x2, y2)), fill=line_gold, width=1)
            case 5:
                draw.ellipse(((310, 310), (1290, 1290)), fill=None, outline=line_gold, width=5)
                coordinates = []
                for i in range(0, 360, 2):
                    x = 800 + 500 * math.sin(i * np.pi / 180)
                    y = 800 + 500 * math.cos(i * np.pi / 180)
                    if (i / 2) % 2 == 1:
                        draw.line(((x, y), (coordinates[-1][0], coordinates[-1][1])), fill=line_gold, width=5)
                    coordinates.append((x, y))
            case 6:
                for i in range(0, 360, 2):
                    x = 800 + 500 * math.sin(i * np.pi / 180)
                    y = 800 + 500 * math.cos(i * np.pi / 180)
                    x1 = x - 5
                    y1 = y - 5
                    x2 = x + 5
                    y2 = y + 5
                    draw.ellipse(((x1, y1), (x2, y2)), fill=line_gold, width=1)
            case 7:
                coordinates = []
                for i in range(0, 360, 1):
                    x = 800 + 500 * math.sin(i * np.pi / 180)
                    y = 800 + 500 * math.cos(i * np.pi / 180)
                    if (i) % 2 == 1:
                        draw.line(((x, y), (coordinates[-1][0], coordinates[-1][1])), fill=line_gold, width=5)
                    coordinates.append((x, y))
        draw.ellipse(((0, 0), (1600, 1600)), fill=None, outline=('#BB9B81'), width=100)
        middle = timelist[indexs][1]
        match middle:
            case 0:
                draw.ellipse(((100, 100), (1500, 1500)), fill=None, outline=line_gold, width=10)
            case 1:
                coordinates = []
                for i in range(0, 360, 3):
                    x = 800 + 700 * math.sin(i * np.pi / 180)
                    y = 800 + 700 * math.cos(i * np.pi / 180)
                    x1 = x - 10
                    y1 = y - 10
                    x2 = x + 10
                    y2 = y + 10
                    x = 800 + 700 * math.sin(i * np.pi / 180)
                    y = 800 + 700 * math.cos(i * np.pi / 180)
                    if len(coordinates) > 0:
                        draw.line(((x, y), (coordinates[-1][0], coordinates[-1][1])), fill=line_gold, width=5)
                    draw.ellipse(((x1, y1), (x2, y2)), fill=line_gold, width=5)
                    coordinates.append((x, y))
                draw.line(((coordinates[0][0], coordinates[0][1]), (coordinates[-1][0], coordinates[-1][1])),
                          fill=line_gold, width=5)
            case 2:
                coordinates = []
                for i in range(0, 360, 2):
                    x = 800 + 700 * math.sin(i * np.pi / 180)
                    y = 800 + 700 * math.cos(i * np.pi / 180)
                    if (i / 2) % 2 == 1:
                        draw.line(((x, y), (coordinates[-1][0], coordinates[-1][1])), fill=line_gold, width=10)
                    coordinates.append((x, y))
        outer = timelist[indexs][2]
        match outer:
            case 0:
                draw.ellipse(((0, 0), (1600, 1600)), fill=None, outline=line_gold, width=20)
            case 1:
                draw.ellipse(((0, 0), (1600, 1600)), fill=None, outline=line_gold, width=15)
                for i in range(0, 360, 3):
                    x = 800 + 785 * math.sin(i * np.pi / 180)
                    y = 800 + 785 * math.cos(i * np.pi / 180)
                    x1 = x - 15
                    y1 = y - 15
                    x2 = x + 15
                    y2 = y + 15
                    draw.ellipse(((x1, y1), (x2, y2)), fill=line_gold, width=3)
            case 2:
                coordinates = []
                for i in range(0, 360, 5):
                    x = 800 + 795 * math.sin(i * np.pi / 180)
                    y = 800 + 795 * math.cos(i * np.pi / 180)
                    if (i / 5) % 2 == 1:
                        draw.line(((x, y), (coordinates[-1][0], coordinates[-1][1])), fill=line_gold, width=15)
                    coordinates.append((x, y))
            case 3:
                draw.ellipse(((0, 0), (1600, 1600)), fill=None, outline=line_gold, width=15)
                coordinates = []
                for i in range(0, 360, 3):
                    x = 800 + 750 * math.sin(i * np.pi / 180)
                    y = 800 + 750 * math.cos(i * np.pi / 180)
                    x1 = 800 + 800 * math.sin(i * np.pi / 180)
                    y1 = 800 + 800 * math.cos(i * np.pi / 180)
                    draw.line(((x, y), (x1, y1)), fill=line_gold, width=10)
                    if (i / 3) % 2 == 1:
                        draw.line(((x, y), (coordinates[-1][0], coordinates[-1][1])), fill=line_gold, width=10)
                    coordinates.append((x, y))
        # 获取own_coin表中的记录数
        db = get_db()
        own_id = db.execute('SELECT COUNT(*) FROM Own_coin').fetchone()[0] + 1
        db.close()
        new_image.save(f'./own/{own_id}.png')  # Save the image

        db = get_db()
        db.execute(
            'INSERT INTO Own_coin (ID, own_id, title, own_photo,coin1_id,coin2_id,coin3_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (id, own_id, text1, f'/own/{own_id}.png', 1, 2, 3))
        db.commit()
        db.close()
        return jsonify({"own_id": own_id})

    def get(self, id):
        # 获取own_id中ID为id的所有数据
        db = get_db()
        own_coin = db.execute('SELECT * FROM Own_coin WHERE ID=?', (id,)).fetchall()
        db.close()
        own_coin = dict(own_coin)
        # own_photo为图片名，从own文件夹中读取图片并转为base64编码
        for c in own_coin:
            own_photo_path = os.path.join(os.getcwd(), 'own', c['own_photo'])
            try:
                with open(own_photo_path, 'rb') as f:
                    own_photo = f.read()
                own_photo_base64 = base64.b64encode(own_photo).decode('utf-8')
                # os.remove(own_photo_path)
                c['own_photo'] = own_photo_base64
            except FileNotFoundError:
                c['own_photo'] = None
        return jsonify(own_coin)


# 获取某一个生成的硬币信息
@api.doc(description='Get a generated coin')
class GeneratedCoin(Resource):
    def get(self, own_id):
        db = get_db()
        try:
            # 获取 Own_coin 数据
            own_coin = db.execute('SELECT * FROM Own_coin WHERE own_id=?', (own_id,)).fetchone()
            if own_coin is None:
                return None, 404
            own_coin = dict(own_coin)

            # own_photo为图片名，从own文件夹中读取图片并转为base64编码
            own_photo_path = f".{own_coin['own_photo']}"

            print(own_photo_path)
            try:
                with open(own_photo_path, 'rb') as f:
                    own_photo = f.read()
                own_coin['own_photo'] = base64.b64encode(own_photo).decode('utf-8')
            except FileNotFoundError:
                own_coin['own_photo'] = None

            # 循环获取每个 coin 的详细信息
            for i in range(1, 4):
                coin = db.execute('SELECT coin_id, coin_name, coin_photo FROM Coin WHERE coin_id=?',
                                  (own_coin[f'coin{i}_id'],)).fetchone()
                if coin:
                    coin = dict(coin)
                    # 获取 Coins 文件夹的路径并读取图片
                    coin_photo_path = os.path.join(os.getcwd(), 'Coins', str(coin['coin_photo']))
                    try:
                        with open(coin_photo_path, 'rb') as f:
                            coin_photo = f.read()
                        coin['coin_photo'] = base64.b64encode(coin_photo).decode('utf-8')
                    except FileNotFoundError:
                        coin['coin_photo'] = None
                own_coin[f'coin{i}_id'] = coin

            return own_coin
        finally:
            # 确保在请求结束时关闭数据库连接
            db.close()


# 添加资源到API
api.add_resource(UserResource, '/user/<string:id>')
api.add_resource(ClassesResource, '/class')
api.add_resource(CoinsResource, '/class/<int:class_id>')
api.add_resource(CoinResource, '/coins/<int:coin_id>')
api.add_resource(HistoryResource, '/history/<string:id>')
api.add_resource(FavoriteResource, '/favorites/<string:id>')
api.add_resource(FavoriteCoinResource, '/favorite/<string:id>/<int:coin_id>')
api.add_resource(RecognitionResource, '/recognition/<string:id>/<int:coin_id>')
api.add_resource(CoinRecognition, '/coin_recognition')
api.add_resource(CoinGeneration, '/coin_generation/<string:id>')
api.add_resource(GeneratedCoin, '/generated_coin/<int:own_id>')
api.add_resource(ClearRecognitionResource, '/clear_recognition/<string:id>')

if __name__ == '__main__':
    app.run(debug=True)